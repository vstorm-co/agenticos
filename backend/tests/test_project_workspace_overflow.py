"""Spill handles retain their Agent origin and the correct cleanup journal."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import Workspace, WorkspaceUnavailableError
from pydantic_ai_backends import StateBackend

from app.agents.audience import RunAudience
from app.agents.capabilities.tool_output_limits import OverflowWriteError, WorkspaceOverflowStore
from app.core.exceptions import NotFoundError
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.sandbox_workspace import SandboxWorkspaceService
from tests.test_agent_runner import _sandbox
from tests.test_project_workspace_bridge import Bridge
from tests.test_project_workspace_bridge import bridge as bridge
from tests.test_run_project_workspace import setup as setup

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_spill_handles_and_writes_stay_in_agent_after_project_target_changes(
    bridge: Bridge,
) -> None:
    journal: list[str] = []
    store = WorkspaceOverflowStore(bridge.port, spill_log=journal)
    handle = await store.write("run-1/call-1", b"first spill")
    await bridge.port.select_execution("project")
    assert await store.read(handle) == b"first spill"
    second = await store.write("run-1/call-2", b"second spill")
    assert await bridge.agent.read_bytes("tool_output/run-1/call-2") == b"second spill"
    assert not await bridge.project.exists("tool_output/run-1/call-1")
    assert not await bridge.project.exists("tool_output/run-1/call-2")
    assert journal == [handle, second]
    with pytest.raises(FileNotFoundError):
        await store.read("tool_output/run-1/unknown")
    await bridge.agent.write_bytes("secret.txt", b"not a spilled result")
    with pytest.raises(FileNotFoundError, match="Unknown tool output"):
        await store.read(str(bridge.agent_root / "secret.txt"))


async def test_lazy_agent_spills_use_its_own_cleanup_journal_and_prune_only_owned_files(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    await bridge.agent.write_bytes("tool_output/another-run/keep", b"other run")
    opened = _sandbox(StateBackend())
    opened.workspace = bridge.agent
    opened.spills = []
    selector = RunProjectWorkspace(
        bridge.project,
        setup.ctx,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        open_agent_executor=AsyncMock(return_value=opened),
        agent_execution_available=True,
    )
    await selector.select(bridge.port.project_id)
    await selector.select_execution("project")
    project_journal: list[str] = []
    store = WorkspaceOverflowStore(selector, spill_log=project_journal)
    handle = await store.write("this-run/call", b"owned spill")
    assert project_journal == []
    assert opened.spills == [handle]
    assert await store.read(handle) == b"owned spill"
    await SandboxWorkspaceService(MagicMock())._prune_spills(opened)
    assert not await bridge.agent.exists("tool_output/this-run/call")
    assert await bridge.agent.read_bytes("tool_output/another-run/keep") == b"other run"
    await selector.close_agent(keep_spills=False)
    setup.service.close.assert_awaited_once_with(opened, keep_spills=False)


async def test_absent_or_wider_agent_workspace_refuses_spill_without_using_project(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    bridge.port.original = None
    store = WorkspaceOverflowStore(bridge.port, spill_log=[])
    with pytest.raises(OverflowWriteError, match="no workspace"):
        await store.write("run/call", b"private tool output")
    setup.service.open_project.assert_not_awaited()
    bridge.port.original = bridge.agent
    bridge.port.original_scope = "channel"
    with pytest.raises(OverflowWriteError, match="wider audience"):
        await store.write("run/call", b"private tool output")
    assert not await bridge.project.exists("tool_output/run/call")


async def test_spill_access_rechecks_project_authority_and_generation(
    bridge: Bridge, setup: SimpleNamespace
) -> None:
    store = WorkspaceOverflowStore(bridge.port)
    handle = await store.write("run/call", b"private tool output")
    setup.guard.side_effect = NotFoundError(message="Project not found", details={})
    with pytest.raises(OverflowWriteError, match="Project not found"):
        await store.write("run/next", b"no")
    with pytest.raises(PermissionError, match="Project not found"):
        await store.read(handle)
    setup.guard.side_effect = None
    setup.guard.return_value.workspace_generation = uuid4()
    with pytest.raises(OverflowWriteError, match="workspace changed"):
        await store.write("run/next", b"no")


async def test_spill_cancellation_is_not_fallback_and_records_no_success(
    bridge: Bridge, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()

    async def cancelled_write(_path: str, _data: bytes) -> None:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge.agent, "write_bytes", cancelled_write)
    journal: list[str] = []
    store = WorkspaceOverflowStore(bridge.port, spill_log=journal)
    task = asyncio.create_task(store.write("run/call", b"input"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert journal == []


async def test_no_spill_journal_is_permitted_for_an_ephemeral_caller(bridge: Bridge) -> None:
    store = WorkspaceOverflowStore(bridge.port)
    handle = await store.write("run/call", b"kept")
    assert await store.read(handle) == b"kept"


async def test_overflow_tree_cannot_escape_by_symlink(bridge: Bridge, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (bridge.agent_root / "tool_output").symlink_to(outside, target_is_directory=True)
    store = WorkspaceOverflowStore(bridge.port)
    with pytest.raises(OverflowWriteError, match="Unknown tool output"):
        await store.write("run/call", b"no")
    assert not (outside / "run/call").exists()


async def test_overflow_path_refuses_cross_drive_and_missing_root() -> None:
    import ntpath
    import posixpath

    workspace = MagicMock(
        spec=Workspace,
        paths=ntpath,
        working_dir=AsyncMock(return_value=r"C:\workspace"),
        resolve=AsyncMock(return_value=r"D:\tool_output\run\call"),
        realpath=AsyncMock(return_value=r"D:\tool_output\run\call"),
    )
    with pytest.raises(FileNotFoundError, match="Unknown tool output"):
        await RunProjectWorkspace._overflow_path(workspace, "tool_output/run/call")
    workspace.paths = posixpath
    workspace.working_dir.return_value = "/workspace"
    workspace.resolve.return_value = "/"
    workspace.realpath.side_effect = FileNotFoundError()
    with pytest.raises(FileNotFoundError):
        await RunProjectWorkspace._overflow_path(workspace, "tool_output/run/call", create=True)
    workspace.resolve.return_value = "/workspace/tool_output/run/call"
    workspace.realpath.side_effect = [
        FileNotFoundError(),
        FileNotFoundError(),
        "/workspace/tool_output",
    ]
    assert (
        await RunProjectWorkspace._overflow_path(workspace, "tool_output/run/call", create=True)
        == "/workspace/tool_output/run/call"
    )
    workspace.realpath.side_effect = FileNotFoundError()
    with pytest.raises(FileNotFoundError):
        await RunProjectWorkspace._overflow_path(workspace, "tool_output/run/call")


async def test_terminal_cleanup_stops_later_spill_admission(bridge: Bridge) -> None:
    bridge.port.stop_admission()
    with pytest.raises(OverflowWriteError, match="closed"):
        await WorkspaceOverflowStore(bridge.port).write("run/call", b"no")
    with pytest.raises(WorkspaceUnavailableError, match="closed"):
        await bridge.port.read_overflow("tool_output/run/call")
