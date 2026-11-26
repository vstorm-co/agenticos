"""Project inputs and command outputs cross explicit, bounded byte boundaries."""

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace, WorkspaceUnavailableError

from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.services.run_project_workspace import MAX_TRANSFER_BYTES, RunProjectWorkspace
from tests.test_run_project_workspace import setup as setup

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@dataclass
class Bridge:
    port: RunProjectWorkspace
    agent: Workspace
    project: Workspace
    agent_root: Path
    project_root: Path


@pytest.fixture
async def bridge(setup: SimpleNamespace, tmp_path: Path) -> Bridge:
    agent_root = tmp_path / "agent"
    project_root = tmp_path / "project"
    agent_root.mkdir()
    project_root.mkdir()
    agent = Workspace(LocalWorkspaceBackend(agent_root))
    project = Workspace(LocalWorkspaceBackend(project_root))
    setup.selector.original = agent
    setup.selector.agent_execution_available = True
    setup.service.open_project.return_value.workspace = project
    setup.guard.return_value.backend = "service"
    await setup.selector.select(uuid4())
    return Bridge(setup.selector, agent, project, agent_root, project_root)


async def test_selected_project_does_not_change_generic_files_or_commands(bridge: Bridge) -> None:
    await bridge.agent.write_bytes("same.bin", b"agent")
    await bridge.project.write_bytes("same.bin", b"project")
    assert await bridge.port.read_bytes("same.bin") == b"agent"
    assert await bridge.port.working_dir() == str(bridge.agent_root)
    read = json.loads(await bridge.port.read_file("same.bin"))
    assert read["content"] == "project"
    assert read["bytes"] == len(b"project")
    assert read["sha256"] == sha256(b"project").hexdigest()
    result = await bridge.port.run(["/bin/pwd"])
    assert result.stdout.strip() == str(bridge.agent_root)
    await bridge.port.make_dir("outputs")
    await bridge.port.write_bytes("outputs/a.bin", b"output")
    assert not await bridge.project.exists("outputs/a.bin")
    assert (await bridge.port.stat("outputs/a.bin")).size == 6
    assert (await bridge.port.list_dir("outputs"))[0].name == "a.bin"
    assert await bridge.port.realpath("outputs/a.bin") == str(bridge.agent_root / "outputs/a.bin")
    await bridge.port.remove("outputs/a.bin")
    assert not await bridge.port.exists("outputs/a.bin")
    await bridge.port.select_execution("project")
    assert await bridge.port.read_bytes("same.bin") == b"project"
    assert await bridge.port.working_dir() == str(bridge.project_root)
    await bridge.port.remove("same.bin")
    assert not await bridge.project.exists("same.bin")


async def test_binary_file_transfer_is_exact_and_is_not_a_mount(bridge: Bridge) -> None:
    data = b"\x00\xff\x80\r\n"
    await bridge.project.write_bytes("input.bin", data)
    receipt = json.loads(await bridge.port.transfer_file("to_agent", "input.bin", "input.bin"))
    assert receipt["agent_path"] == "input.bin"
    assert receipt["agent_absolute_path"] == str(bridge.agent_root / "input.bin")
    assert receipt["sha256"] == sha256(data).hexdigest()
    assert receipt["bytes"] == len(data)
    assert receipt["direction"] == "to_agent"
    assert bridge.port.execution_target == "agent"
    assert await bridge.agent.read_bytes("input.bin") == data
    await bridge.agent.write_bytes("input.bin", b"new")
    assert await bridge.project.read_bytes("input.bin") == data
    receipt = json.loads(await bridge.port.transfer_file("from_agent", "report.bin", "input.bin"))
    assert receipt["sha256"] == sha256(b"new").hexdigest()
    assert await bridge.project.read_bytes("report.bin") == b"new"


@pytest.mark.parametrize("direction", ["to_agent", "from_agent"])
async def test_existing_destination_requires_current_digest(
    bridge: Bridge, direction: Literal["to_agent", "from_agent"]
) -> None:
    await bridge.project.write_bytes("file.bin", b"project")
    await bridge.agent.write_bytes("file.bin", b"agent")
    destination = bridge.agent if direction == "to_agent" else bridge.project
    before = await destination.read_bytes("file.bin")
    with pytest.raises(ConcurrentChangeError, match="destination exists"):
        await bridge.port.transfer_file(direction, "file.bin", "file.bin")
    with pytest.raises(ConcurrentChangeError, match="destination changed"):
        await bridge.port.transfer_file(direction, "file.bin", "file.bin", "0" * 64)
    assert await destination.read_bytes("file.bin") == before
    await bridge.port.transfer_file(direction, "file.bin", "file.bin", sha256(before).hexdigest())
    assert await destination.read_bytes("file.bin") == (
        b"project" if direction == "to_agent" else b"agent"
    )


async def test_missing_expected_destination_is_a_conflict(bridge: Bridge) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    with pytest.raises(ConcurrentChangeError, match="no longer exists"):
        await bridge.port.transfer_file("to_agent", "input.bin", "missing.bin", "0" * 64)
    assert not await bridge.agent.exists("missing.bin")


@pytest.mark.parametrize("value", ["", "abc", "g" * 64, "A" * 64])
async def test_invalid_digest_is_refused_before_open(bridge: Bridge, value: str) -> None:
    with pytest.raises(BadRequestError, match="SHA-256"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin", value)


@pytest.mark.parametrize(
    "path", ["../outside", ".agenticos/private", "a/../../outside", "bad\x00name"]
)
async def test_transfer_paths_are_confined(bridge: Bridge, path: str) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    with pytest.raises(BadRequestError):
        await bridge.port.transfer_file("to_agent", "input.bin", path)


async def test_symlink_to_outside_is_refused(bridge: Bridge, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (bridge.agent_root / "escape").symlink_to(outside, target_is_directory=True)
    await bridge.project.write_bytes("input.bin", b"input")
    with pytest.raises(BadRequestError):
        await bridge.port.transfer_file("to_agent", "input.bin", "escape/copied.bin")
    assert not (outside / "copied.bin").exists()


async def test_transfer_refuses_unknown_size_and_directory(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.project.make_dir("folder")
    with pytest.raises(BadRequestError, match="known size"):
        await bridge.port.transfer_file("to_agent", "folder", "output.bin")
    await bridge.project.write_bytes("input.bin", b"input")
    monkeypatch.setattr(
        bridge.project, "stat", AsyncMock(return_value=SimpleNamespace(is_dir=False, size=None))
    )
    with pytest.raises(BadRequestError, match="known size"):
        await bridge.port.transfer_file("to_agent", "input.bin", "output.bin")


async def test_transfer_checks_declared_and_actual_size(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    monkeypatch.setattr(
        bridge.project,
        "stat",
        AsyncMock(return_value=SimpleNamespace(is_dir=False, size=MAX_TRANSFER_BYTES + 1)),
    )
    with pytest.raises(BadRequestError, match="known size"):
        await bridge.port.transfer_file("to_agent", "input.bin", "output.bin")
    monkeypatch.setattr(
        bridge.project, "stat", AsyncMock(return_value=SimpleNamespace(is_dir=False, size=1))
    )
    monkeypatch.setattr(
        bridge.project, "read_bytes", AsyncMock(return_value=b"x" * (MAX_TRANSFER_BYTES + 1))
    )
    with pytest.raises(BadRequestError, match="grew beyond"):
        await bridge.port.transfer_file("to_agent", "input.bin", "output.bin")
    assert not await bridge.agent.exists("output.bin")


async def test_transfer_rechecks_access_generation_and_write_scope(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    await bridge.agent.write_bytes("input.bin", b"input")
    bridge.port.granted_scopes = frozenset({"projects:read"})
    with pytest.raises(AuthorizationError, match="writes"):
        await bridge.port.transfer_file("from_agent", "input.bin", "input.bin")
    setup.guard.side_effect = NotFoundError(message="Project not found", details={})
    with pytest.raises(PermissionError, match="Project not found"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    with pytest.raises(PermissionError, match="Project not found"):
        await bridge.port.exists("input.bin")
    setup.guard.side_effect = None
    setup.guard.return_value.workspace_generation = uuid4()
    with pytest.raises(PermissionError, match="workspace changed"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    with pytest.raises(PermissionError, match="workspace changed"):
        await bridge.port.exists("input.bin")


async def test_transfer_refuses_wider_agent_audience_and_closed_run(bridge: Bridge) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    bridge.port.original_scope = "channel"
    with pytest.raises(WorkspaceUnavailableError, match="wider audience"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    bridge.port.original_scope = None
    bridge.port.stop_admission()
    with pytest.raises(WorkspaceUnavailableError, match="closed"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")


async def test_selection_cannot_change_while_transfer_is_awaiting(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    original_read = bridge.project.read_bytes

    async def move_selection(path: str) -> bytes:
        data = await original_read(path)
        bridge.port.project_id = uuid4()
        return data

    monkeypatch.setattr(bridge.project, "read_bytes", move_selection)
    with pytest.raises(ConcurrentChangeError, match="selection changed"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    assert not await bridge.agent.exists("input.bin")


async def test_transfer_needs_project_selection(bridge: Bridge) -> None:
    await bridge.port.select(None)
    with pytest.raises(AuthorizationError, match="Select a project"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")


async def test_transfer_detects_destination_changed_after_write(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    monkeypatch.setattr(bridge.agent, "read_bytes", AsyncMock(return_value=b"concurrent overwrite"))
    with pytest.raises(ConcurrentChangeError, match="while verifying"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")


async def test_eight_mebibyte_transfer_boundary_is_supported(bridge: Bridge) -> None:
    data = b"x" * MAX_TRANSFER_BYTES
    await bridge.project.write_bytes("input.bin", data)
    result = json.loads(await bridge.port.transfer_file("to_agent", "input.bin", "input.bin"))
    assert result["bytes"] == MAX_TRANSFER_BYTES
    assert result["sha256"] == sha256(data).hexdigest()


async def test_project_transfer_preserves_fresh_read_guard_after_continuation(
    bridge: Bridge,
) -> None:
    await bridge.project.write_bytes("report.bin", b"old")
    await bridge.agent.write_bytes("report.bin", b"new")
    bridge.port._require_continuation_reads = True
    with pytest.raises(WorkspaceUnavailableError, match="after continuation"):
        await bridge.port.transfer_file(
            "from_agent", "report.bin", "report.bin", sha256(b"old").hexdigest()
        )
    await bridge.port.read_file("report.bin")
    await bridge.port.transfer_file(
        "from_agent", "report.bin", "report.bin", sha256(b"old").hexdigest()
    )
    assert await bridge.project.read_bytes("report.bin") == b"new"


async def test_closed_during_source_read_does_not_write(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    original_read = bridge.project.read_bytes

    async def close_during_read(path: str) -> bytes:
        data = await original_read(path)
        bridge.port.stop_admission()
        return data

    monkeypatch.setattr(bridge.project, "read_bytes", close_during_read)
    with pytest.raises(WorkspaceUnavailableError, match="closed"):
        await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    assert not await bridge.agent.exists("input.bin")


async def test_read_only_project_does_not_block_agent_output(bridge: Bridge) -> None:
    bridge.port.granted_scopes = frozenset({"projects:read"})
    await bridge.port.write_bytes("report.bin", b"own output")
    assert await bridge.agent.read_bytes("report.bin") == b"own output"
    assert not await bridge.project.exists("report.bin")


async def test_receipt_relative_agent_path_roundtrips_and_absolute_input_is_refused(
    bridge: Bridge,
) -> None:
    await bridge.project.write_bytes("input.bin", b"input")
    receipt = json.loads(await bridge.port.transfer_file("to_agent", "input.bin", "input.bin"))
    await bridge.port.transfer_file("from_agent", "returned.bin", receipt["agent_path"])
    assert await bridge.project.read_bytes("returned.bin") == b"input"
    with pytest.raises(BadRequestError):
        await bridge.port.transfer_file(
            "to_agent", "input.bin", str(bridge.agent_root.parent / "outside.bin")
        )


async def test_windows_canonical_path_is_checked_inside_its_own_workspace() -> None:
    import ntpath

    workspace = MagicMock(
        spec=Workspace,
        paths=ntpath,
        platform="windows",
        resolve=AsyncMock(return_value=r"C:\workspace\input.bin"),
        realpath=AsyncMock(return_value=r"C:\workspace\input.bin"),
        working_dir=AsyncMock(return_value=r"C:\workspace"),
    )
    assert await RunProjectWorkspace._file_path(workspace, "input.bin") == "input.bin"
    workspace.realpath.return_value = r"C:\outside\private.bin"
    with pytest.raises(BadRequestError):
        await RunProjectWorkspace._file_path(workspace, "input.bin")

    workspace.realpath.return_value = r"D:\outside\private.bin"
    with pytest.raises(BadRequestError, match="inside the workspace"):
        await RunProjectWorkspace._file_path(workspace, "input.bin")


async def test_authorized_project_first_use_initializes_staging_once_for_delegates(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    bridge.port.conversation_project_id = bridge.port.project_id

    async def restore(_db: object) -> None:
        await bridge.project.write_bytes("restored.txt", b"earlier upload")

    initializer = AsyncMock(side_effect=restore)
    bridge.port.initialize_project = initializer
    child = bridge.port.snapshot_for_delegate()
    assert "earlier upload" in await child.read_file("restored.txt")
    assert "earlier upload" in await bridge.port.read_file("restored.txt")
    initializer.assert_awaited_once()
    setup.service.open_project.assert_awaited()


async def test_project_initializer_cannot_run_under_revoked_or_changed_authority(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    bridge.port.conversation_project_id = bridge.port.project_id
    initializer = AsyncMock()
    bridge.port.initialize_project = initializer
    setup.guard.side_effect = NotFoundError(message="Project not found", details={})
    with pytest.raises(PermissionError, match="Project not found"):
        await bridge.port.files()
    initializer.assert_not_awaited()
    setup.guard.side_effect = None
    setup.guard.return_value.workspace_generation = uuid4()
    with pytest.raises(PermissionError, match="workspace changed"):
        await bridge.port.files()
    initializer.assert_not_awaited()


async def test_project_initialization_serializes_and_still_obeys_root_cleanup(
    bridge: Bridge,
) -> None:
    import asyncio

    bridge.port.conversation_project_id = bridge.port.project_id
    entered, release = asyncio.Event(), asyncio.Event()

    async def initialize(_db: object) -> None:
        entered.set()
        await release.wait()

    initializer = AsyncMock(side_effect=initialize)
    bridge.port.initialize_project = initializer
    first = asyncio.create_task(bridge.port.files())
    await entered.wait()
    second = asyncio.create_task(bridge.port.files())
    release.set()
    await asyncio.gather(first, second)
    initializer.assert_awaited_once()
    bridge.port._project_initialized = False
    bridge.port.initialize_project = AsyncMock(side_effect=lambda _db: bridge.port.stop_admission())
    with pytest.raises(WorkspaceUnavailableError, match="closed"):
        await bridge.port.files()


async def test_imports_are_not_automatic_outputs_and_do_not_hide_genuine_results(
    bridge: Bridge,
) -> None:
    from pydantic_ai_backends import StateBackend

    from app.services.agent_runner import AgentRunnerService
    from tests.test_agent_runner import _prepared, _sandbox

    prepared = _prepared()
    prepared.workspace = _sandbox(StateBackend())
    prepared.workspace.workspace = bridge.agent
    prepared.workspace.scope = "conversation"
    prepared.workspace_at_start = set()
    prepared.project_workspace = bridge.port
    await bridge.agent.write_bytes("result.txt", b"authored before the transfer")
    await bridge.project.write_bytes("input.bin", b"input")
    await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    await AgentRunnerService._collect_outbound(prepared)
    assert [item.filename for item in prepared.outbound] == ["result.txt"]
    assert bridge.port.outbound_baseline("agent", None) is None


async def test_publishing_a_result_to_project_does_not_attach_it_twice(bridge: Bridge) -> None:
    from pydantic_ai_backends import StateBackend

    from app.services.agent_runner import AgentRunnerService
    from tests.test_agent_runner import _prepared, _sandbox

    prepared = _prepared()
    prepared.workspace = _sandbox(StateBackend())
    prepared.workspace.workspace = bridge.project
    prepared.workspace.scope = "project"
    prepared.workspace_at_start = {"./input.bin"}
    prepared.project_workspace = bridge.port
    agent = _sandbox(StateBackend())
    agent.workspace = bridge.agent
    bridge.port.agent_workspace = agent
    bridge.port.agent_workspace_at_start = set()
    await bridge.project.write_bytes("input.bin", b"input")
    await bridge.port.transfer_file("to_agent", "input.bin", "input.bin")
    await bridge.agent.write_bytes("result.txt", b"result")
    await bridge.port.transfer_file("from_agent", "result.txt", "result.txt")
    await AgentRunnerService._collect_outbound(prepared)
    assert [item.filename for item in prepared.outbound] == ["result.txt"]


async def test_project_staging_baseline_is_accepted_only_after_its_transaction_commits(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.services import run_project_workspace as module

    events: list[str] = []
    bridge.port.conversation_project_id = bridge.port.project_id

    @asynccontextmanager
    async def committed():
        yield MagicMock()
        events.append("committed")

    def settled() -> None:
        assert events == ["committed"]
        events.append("accepted")

    bridge.port.initialize_project = AsyncMock(return_value=settled)
    monkeypatch.setattr(module, "get_db_context", committed)
    await bridge.port.files()
    assert events == ["committed", "accepted", "committed"]
    assert bridge.port._project_initialized


async def test_failed_staging_commit_does_not_accept_a_baseline_or_open_the_reader(
    bridge: Bridge, setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import asynccontextmanager

    from app.services import run_project_workspace as module

    bridge.port.conversation_project_id = bridge.port.project_id
    settled = MagicMock()
    bridge.port.initialize_project = AsyncMock(return_value=settled)

    @asynccontextmanager
    async def failed_commit():
        yield MagicMock()
        raise RuntimeError("commit refused")

    monkeypatch.setattr(module, "get_db_context", failed_commit)
    with pytest.raises(RuntimeError, match="commit refused"):
        await bridge.port.files()
    assert not bridge.port._project_initialized
    settled.assert_not_called()
    setup.service.open_project.assert_not_awaited()


async def test_binary_transfer_observation_allows_fresh_publication_after_continuation(
    bridge: Bridge,
) -> None:
    original = b"\x00\xfforiginal"
    updated = b"\x00\xffupdated"
    await bridge.project.write_bytes("report.bin", original)
    bridge.port._require_continuation_reads = True

    receipt = json.loads(await bridge.port.transfer_file("to_agent", "report.bin", "report.bin"))
    await bridge.agent.write_bytes("report.bin", updated)
    await bridge.port.transfer_file("from_agent", "report.bin", "report.bin", receipt["sha256"])

    assert await bridge.project.read_bytes("report.bin") == updated


async def test_binary_transfer_observation_does_not_allow_an_unobserved_project_change(
    bridge: Bridge,
) -> None:
    await bridge.project.write_bytes("report.bin", b"\x00\xfforiginal")
    bridge.port._require_continuation_reads = True
    await bridge.port.transfer_file("to_agent", "report.bin", "report.bin")
    changed = b"\x00\xffchanged by another writer"
    await bridge.project.write_bytes("report.bin", changed)
    await bridge.agent.write_bytes("report.bin", b"\x00\xffupdated")

    with pytest.raises(WorkspaceUnavailableError, match="changed since it was read"):
        await bridge.port.transfer_file(
            "from_agent", "report.bin", "report.bin", sha256(changed).hexdigest()
        )
    assert await bridge.project.read_bytes("report.bin") == changed
