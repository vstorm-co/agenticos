"""Selecting a project changes files, never the caller's identity or conversation."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.services import run_project_workspace as module
from app.services.run_project_workspace import RunProjectWorkspace
from app.services.sandbox_workspace import WorkspaceFlushFailure
from tests.workspaces import document_workspace

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    db = MagicMock()

    @asynccontextmanager
    async def session() -> AsyncGenerator[MagicMock]:
        yield db

    monkeypatch.setattr(module, "get_db_context", session)
    member = AsyncMock(return_value=SimpleNamespace(role="member", is_app_admin=False))
    guard = AsyncMock(return_value=SimpleNamespace(id=uuid4(), name="HN Wiki", backend="state"))
    project_workspace = document_workspace()
    service = SimpleNamespace(
        open_project=AsyncMock(return_value=SimpleNamespace(workspace=project_workspace)),
        close=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(module, "member_context", member)
    monkeypatch.setattr(module, "project_for_workspace", guard)
    monkeypatch.setattr(module, "SandboxWorkspaceService", lambda _: service)
    original = document_workspace()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    selector = RunProjectWorkspace(original, ctx)
    return SimpleNamespace(
        selector=selector,
        original=original,
        project=project_workspace,
        guard=guard,
        member=member,
        service=service,
        ctx=ctx,
    )


async def test_select_files_and_reset_without_copying_private_content(
    setup: SimpleNamespace,
) -> None:
    await setup.original.write_text("private.txt", "private conversation file")
    await setup.project.write_text("index.md", "project index")
    project_id = uuid4()
    assert "HN Wiki" in await setup.selector.select(project_id)
    assert setup.service.open_project.await_count == 0
    assert await setup.selector.workspace.read_text("index.md") == "project index"
    assert not await setup.selector.workspace.exists("private.txt")
    await setup.selector.workspace.write_text("report.md", "report")
    assert await setup.project.read_text("report.md") == "report"
    assert not await setup.original.exists("report.md")
    assert "Restored" in await setup.selector.select(None)
    assert await setup.selector.workspace.read_text("private.txt") == "private conversation file"
    assert setup.selector.ref is None
    await setup.selector.workspace.write_text("local.md", "original workspace")
    assert await setup.original.read_text("local.md") == "original workspace"
    await setup.selector.workspace.remove("local.md")
    assert not await setup.original.exists("local.md")


@pytest.mark.parametrize("unlinked", [True, False])
async def test_no_publisher_or_subjectless_authority(
    setup: SimpleNamespace, unlinked: bool
) -> None:
    selector = RunProjectWorkspace(
        setup.original,
        AuthContext(
            user_id=setup.ctx.user_id if unlinked else None,
            organization_id=setup.ctx.organization_id,
            role="owner",
            subject_is_publisher_fallback=unlinked,
        ),
    )
    with pytest.raises(AuthorizationError):
        await selector.select(uuid4())
    selector.project_id = uuid4()
    with pytest.raises(PermissionError):
        await selector.workspace.read_text("index.md")
    setup.guard.assert_not_awaited()
    setup.service.open_project.assert_not_awaited()


async def test_rechecks_membership_role_and_project_on_every_operation(
    setup: SimpleNamespace,
) -> None:
    await setup.selector.select(uuid4())
    assert setup.guard.await_args.args[1].role == "member"
    assert setup.guard.await_args.args[1].is_app_admin is False
    setup.guard.side_effect = NotFoundError(message="Project not found")
    with pytest.raises(PermissionError, match="Project not found"):
        await setup.selector.workspace.write_text("denied.md", "no")
    assert not await setup.project.exists("denied.md")
    setup.guard.side_effect = None
    setup.member.return_value = None
    with pytest.raises(PermissionError, match="membership"):
        await setup.selector.workspace.list_dir(".")
    with pytest.raises(AuthorizationError, match="membership"):
        await setup.selector.select(uuid4())


async def test_routine_source_ceiling_cannot_be_widened(setup: SimpleNamespace) -> None:
    check = MagicMock(side_effect=AuthorizationError(message="Review routine sources first"))
    selector = RunProjectWorkspace(setup.original, setup.ctx, require_project=check)
    with pytest.raises(AuthorizationError, match="routine sources"):
        await selector.select(uuid4())
    assert selector.project_id is None
    setup.service.open_project.assert_not_awaited()
    selector.project_id = uuid4()
    with pytest.raises(PermissionError, match="routine sources"):
        await selector.workspace.exists("index.md")


async def test_project_failure_closes_and_flush_failure_is_not_success(
    setup: SimpleNamespace,
) -> None:
    await setup.selector.select(uuid4())
    with pytest.raises(FileNotFoundError):
        await setup.selector.workspace.read_text("missing.md")
    assert setup.service.close.await_count > 0
    setup.service.close.return_value = WorkspaceFlushFailure(
        error=SimpleNamespace(message="Concurrent project edit; write not saved")
    )
    with pytest.raises(WorkspaceUnavailableError, match="not saved"):
        await setup.selector.workspace.write_text("report.md", "unsaved")


async def test_filesystem_operations_and_file_only_shell_refusal(setup: SimpleNamespace) -> None:
    await setup.selector.select(uuid4())
    await setup.selector.workspace.make_dir("notes")
    await setup.selector.workspace.write_bytes("notes/a.txt", b"a")
    assert (await setup.selector.workspace.stat("notes/a.txt")).size == 1
    assert (await setup.selector.workspace.list_dir("notes"))[0].name == "a.txt"
    assert await setup.selector.workspace.realpath("notes/a.txt")
    await setup.selector.workspace.remove("notes/a.txt")
    assert not await setup.selector.workspace.exists("notes/a.txt")
    with pytest.raises(WorkspaceUnavailableError, match="files only"):
        await setup.selector.workspace.run(["pwd"])


async def test_command_backend_uses_selected_project(setup: SimpleNamespace, tmp_path) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    setup.service.open_project.return_value.workspace = Workspace(LocalWorkspaceBackend(tmp_path))
    await setup.selector.select(uuid4())
    result = await setup.selector.workspace.run(["/bin/pwd"], timeout=5)
    assert result.exit_code == 0
    assert result.stdout.strip() == str(tmp_path.resolve())
    (tmp_path / "subfolder").mkdir()
    result = await setup.selector.workspace.run(["/bin/pwd"], cwd="subfolder", timeout=5)
    assert result.stdout.strip() == str((tmp_path / "subfolder").resolve())


async def test_cancellation_closes_the_project_transport(setup: SimpleNamespace) -> None:
    import asyncio

    entered = asyncio.Event()

    async def wait_for_cancel(path: str) -> bytes:
        entered.set()
        await asyncio.Event().wait()
        return b"unreachable"

    setup.service.open_project.return_value.workspace = MagicMock(
        read_bytes=wait_for_cancel, working_dir=AsyncMock(return_value="/")
    )
    await setup.selector.select(uuid4())
    task = asyncio.create_task(setup.selector.read_bytes("/index.md"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    setup.service.close.assert_awaited_once()


async def test_selection_tool_is_a_barrier_and_returns_refusals() -> None:
    from app.agents.capabilities.sandbox._project import project_tools

    unavailable = project_tools(None).tools["select_project_workspace"]
    assert unavailable.sequential
    assert "unavailable" in await unavailable.function()
    port = SimpleNamespace(project_id=None, select=AsyncMock(return_value="selected"))
    tool = project_tools(port).tools["select_project_workspace"]
    project_id = uuid4()
    assert await tool.function(project_id) == "selected"
    port.select.assert_awaited_once_with(project_id)
    port.select.side_effect = NotFoundError(message="Project not found")
    assert await tool.function(project_id) == "Project not found"


async def test_provider_backend_is_preserved_until_selection(setup: SimpleNamespace) -> None:
    assert setup.selector.workspace.backend is setup.original.backend
    await setup.selector.select(uuid4())
    assert setup.selector.workspace.backend is setup.selector
    await setup.selector.select(None)
    assert setup.selector.workspace.backend is setup.original.backend


async def test_unavailable_project_provider_is_a_controlled_tool_failure(
    setup: SimpleNamespace,
) -> None:
    await setup.selector.select(uuid4())
    setup.service.open_project.side_effect = NotFoundError(message="Sandbox connection not found")
    with pytest.raises(PermissionError, match="Sandbox connection not found"):
        await setup.selector.workspace.list_dir(".")
    setup.service.close.assert_not_awaited()


async def test_a_stale_read_cannot_overwrite_or_delete_another_project_edit(
    setup: SimpleNamespace,
) -> None:
    await setup.selector.select(uuid4())
    await setup.project.write_text("report.md", "original")
    await setup.selector.workspace.read_text("report.md")
    await setup.project.write_text("report.md", "another writer")
    with pytest.raises(WorkspaceUnavailableError, match="changed since"):
        await setup.selector.workspace.write_text("report.md", "stale replacement")
    with pytest.raises(WorkspaceUnavailableError, match="changed since"):
        await setup.selector.workspace.remove("report.md")
    assert await setup.project.read_text("report.md") == "another writer"
    await setup.selector.workspace.read_text("report.md")
    await setup.selector.workspace.write_text("report.md", "refreshed replacement")
    assert await setup.project.read_text("report.md") == "refreshed replacement"
    await setup.project.remove("report.md")
    with pytest.raises(WorkspaceUnavailableError, match="changed since"):
        await setup.selector.workspace.write_text("report.md", "resurrected stale file")
