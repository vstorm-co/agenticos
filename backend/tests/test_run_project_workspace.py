"""Selecting a project changes files, never the caller's identity or conversation."""

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceUnavailableError

from app.agents.audience import RunAudience
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
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
    guard = AsyncMock(
        return_value=SimpleNamespace(
            id=uuid4(),
            name="HN Wiki",
            backend="state",
            workspace_generation=uuid4(),
            description="Shared reference",
            instructions="Keep the sources.",
            visibility="private",
        )
    )
    project_workspace = document_workspace()
    service = SimpleNamespace(
        open_project=AsyncMock(
            return_value=SimpleNamespace(workspace=project_workspace, row_id=None)
        ),
        close=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(module, "member_context", member)
    monkeypatch.setattr(module, "project_for_workspace", guard)
    monkeypatch.setattr(module, "SandboxWorkspaceService", lambda _: service)
    original = document_workspace()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    selector = RunProjectWorkspace(
        original,
        ctx,
        audience=RunAudience(user_id=ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
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
    assert "Cleared" in await setup.selector.select(None)
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
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
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
    selector = RunProjectWorkspace(
        setup.original,
        setup.ctx,
        require_project=check,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
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
        await setup.selector.run(["pwd"])


async def test_command_backend_uses_selected_project(setup: SimpleNamespace, tmp_path) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    setup.service.open_project.return_value.workspace = Workspace(LocalWorkspaceBackend(tmp_path))
    setup.guard.return_value.backend = "service"
    await setup.selector.select(uuid4())
    await setup.selector.select_execution("project")
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
    await asyncio.wait_for(entered.wait(), timeout=5)
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


async def test_selecting_files_does_not_move_the_agent_command_target(
    setup: SimpleNamespace, tmp_path: Path
) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    agent_root, project_root = tmp_path / "agent", tmp_path / "project"
    agent_root.mkdir()
    project_root.mkdir()
    (agent_root / "private.txt").write_text("private agent file")
    (project_root / "reference.txt").write_text("project reference")
    setup.selector.original = Workspace(LocalWorkspaceBackend(agent_root))
    setup.selector.agent_execution_available = True
    setup.service.open_project.return_value.workspace = Workspace(
        LocalWorkspaceBackend(project_root)
    )
    setup.guard.return_value.backend = "service"
    selection = await setup.selector.select(uuid4())
    assert '"execution_target": "agent"' in selection
    assert await setup.selector.workspace.read_text("reference.txt") == "project reference"
    first = await setup.selector.workspace.run(["/bin/pwd"], timeout=5)
    assert first.stdout.strip() == str(agent_root.resolve())
    assert not (agent_root / "reference.txt").exists()
    assert not (project_root / "private.txt").exists()
    await setup.selector.select_execution("project")
    second = await setup.selector.workspace.run(["/bin/pwd"], timeout=5)
    assert second.stdout.strip() == str(project_root.resolve())


async def test_files_only_agent_has_real_project_files_without_an_executor(
    setup: SimpleNamespace,
) -> None:
    selector = RunProjectWorkspace(
        None,
        setup.ctx,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    await setup.project.write_text("notes.md", "authoritative project content")
    result = await selector.select(uuid4())
    assert '"agent_execution_available": false' in result
    setup.service.open_project.assert_not_awaited()
    assert "authoritative project content" in await selector.read_file("notes.md")
    await selector.write_file("draft.md", "agreed draft")
    assert await setup.project.read_text("draft.md") == "agreed draft"
    with pytest.raises(AuthorizationError, match="no command"):
        await selector.select_execution("agent")
    with pytest.raises(AuthorizationError, match="files only"):
        await selector.select_execution("project")


@pytest.mark.parametrize("shared", [False, True])
async def test_room_and_unrelated_shared_transcript_do_not_receive_project_context(
    setup: SimpleNamespace, shared: bool
) -> None:
    setup.selector.audience = RunAudience(
        user_id=setup.ctx.user_id,
        room_key=None if shared else "room:mattermost:public",
        shared_transcript=shared,
    )
    with pytest.raises(AuthorizationError, match="private conversation"):
        await setup.selector.select(uuid4())
    setup.guard.assert_not_awaited()
    setup.service.open_project.assert_not_awaited()
    with pytest.raises(AuthorizationError, match="private conversation"):
        await setup.selector.search("secret")


async def test_the_admitted_project_is_allowed_in_its_own_shared_web_chat(
    setup: SimpleNamespace,
) -> None:
    admitted = setup.guard.return_value.id
    setup.selector.audience = RunAudience(user_id=setup.ctx.user_id, shared_transcript=True)
    setup.selector.conversation_project_id = admitted
    assert "HN Wiki" in await setup.selector.select(admitted)
    with pytest.raises(AuthorizationError):
        await setup.selector.select(uuid4())


async def test_workspace_generation_change_requires_reselection_even_after_checkpoint(
    setup: SimpleNamespace,
) -> None:
    selected = uuid4()
    await setup.selector.select(selected)
    generation = setup.selector.project_generation
    restored = RunProjectWorkspace(
        setup.original,
        setup.ctx,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
    )
    restored.restore(selected, generation, "agent", True)
    setup.guard.return_value.workspace_generation = uuid4()
    with pytest.raises(PermissionError, match="workspace changed"):
        await restored.files()
    restored.restore(selected, None, None)
    with pytest.raises(PermissionError, match="workspace changed"):
        await restored.files()
    await restored.select(selected)
    assert '"namespace": "project"' in await restored.files()


async def test_project_scopes_cannot_be_bypassed_by_the_legacy_workspace_proxy(
    setup: SimpleNamespace,
) -> None:
    setup.selector.granted_scopes = frozenset()
    with pytest.raises(AuthorizationError, match="disabled"):
        await setup.selector.select(uuid4())
    setup.selector.granted_scopes = frozenset({"projects:read"})
    await setup.selector.select(uuid4())
    with pytest.raises(PermissionError, match="writes are disabled"):
        await setup.selector.workspace.write_text("private.txt", "refused")
    with pytest.raises(AuthorizationError, match="writes are disabled"):
        await setup.selector.write_file("private.txt", "refused")


async def test_private_project_context_cannot_be_written_to_a_wider_agent_workspace_after_clear(
    setup: SimpleNamespace,
) -> None:
    setup.selector.original_scope = "agent"
    setup.selector.agent_execution_available = True
    await setup.selector.select(uuid4())
    with pytest.raises(AuthorizationError, match="wider audience"):
        await setup.selector.select_execution("agent")
    await setup.selector.select(None)
    assert setup.selector.project_context_observed
    with pytest.raises(WorkspaceUnavailableError, match="wider audience"):
        await setup.selector.workspace.write_text("leak.md", "project reference")


async def test_project_executor_never_silently_replaces_local_consent_or_another_project(
    setup: SimpleNamespace,
) -> None:
    setup.guard.return_value.backend = "service"
    first = uuid4()
    await setup.selector.select(first)
    setup.selector.allow_project_execution = False
    with pytest.raises(AuthorizationError, match="Local computer"):
        await setup.selector.select_execution("project")
    setup.selector.allow_project_execution = True
    await setup.selector.select_execution("project")
    with pytest.raises(AuthorizationError, match="another project"):
        await setup.selector.select(uuid4())
    assert setup.selector.project_id == first
    setup.service.open_project.assert_not_awaited()


async def test_lazy_agent_executor_is_reused_until_finish_and_keeps_its_own_outputs(
    setup: SimpleNamespace, tmp_path: Path
) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    opened = SimpleNamespace(workspace=Workspace(LocalWorkspaceBackend(tmp_path)), row_id=uuid4())
    factory = AsyncMock(return_value=opened)
    selector = RunProjectWorkspace(
        setup.original,
        setup.ctx,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        open_agent_executor=factory,
        agent_execution_available=True,
    )
    await selector.select(uuid4())
    factory.assert_not_awaited()
    await selector.workspace.run(
        [sys.executable, "-c", "from pathlib import Path; Path('report.txt').write_text('result')"],
        timeout=5,
    )
    read = await selector.workspace.run(["/bin/cat", "report.txt"], timeout=5)
    assert read.stdout == "result"
    assert selector.agent_workspace_at_start == set()
    assert selector.origins[opened.row_id]["kind"] == "agent"
    factory.assert_awaited_once()
    setup.service.close.assert_not_awaited()
    assert not await setup.project.exists("report.txt")
    await selector.close_agent(keep_spills=False)
    setup.service.close.assert_awaited_once_with(opened, keep_spills=False)
    assert selector.agent_workspace is None
    assert await selector.close_agent(keep_spills=False) is None


@pytest.mark.parametrize("path", ["../outside.txt", ".agenticos/private.txt", "../etc/passwd"])
async def test_project_text_tools_refuse_reserved_or_escaping_paths(
    setup: SimpleNamespace, path: str
) -> None:
    await setup.selector.select(uuid4())
    with pytest.raises(BadRequestError):
        await setup.selector.write_file(path, "refused")


async def test_project_text_tools_refuse_symlink_escape_and_reserved_alias(
    setup: SimpleNamespace, tmp_path: Path
) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private")
    (root / ".agenticos").mkdir()
    (root / ".agenticos" / "secret.txt").write_text("reserved")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "alias").symlink_to(root / ".agenticos", target_is_directory=True)
    setup.service.open_project.return_value.workspace = Workspace(LocalWorkspaceBackend(root))
    await setup.selector.select(uuid4())
    for path in ("escape/secret.txt", "alias/secret.txt"):
        with pytest.raises((BadRequestError, PermissionError)):
            await setup.selector.read_file(path)
    with pytest.raises((BadRequestError, PermissionError)):
        await setup.selector.write_file("escape/new/note.txt", "refused")
    assert not (outside / "new").exists()


@pytest.mark.parametrize("content", [b"\xff", b"x" * 256_001])
async def test_project_text_reads_refuse_binary_or_large_files(
    setup: SimpleNamespace, content: bytes
) -> None:
    await setup.project.write_bytes("data.bin", content)
    await setup.selector.select(uuid4())
    with pytest.raises(BadRequestError):
        await setup.selector.read_file("data.bin")


async def test_agent_executor_rechecks_membership_after_cached_initialization(
    setup: SimpleNamespace,
) -> None:
    opened = SimpleNamespace(workspace=setup.original, row_id=None)
    factory = AsyncMock(return_value=opened)
    selector = RunProjectWorkspace(
        setup.original,
        setup.ctx,
        audience=RunAudience(user_id=setup.ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        open_agent_executor=factory,
    )
    async with selector._open_agent():
        pass
    setup.member.return_value = None
    with pytest.raises(AuthorizationError, match="membership"):
        async with selector._open_agent():
            pytest.fail("revoked executor was returned")
    factory.assert_awaited_once()
    await selector.close_agent(keep_spills=False)


async def test_aliases_cannot_bypass_the_read_revision_barrier(
    setup: SimpleNamespace, tmp_path: Path
) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    (tmp_path / "actual.txt").write_text("initial")
    (tmp_path / "alias.txt").symlink_to(tmp_path / "actual.txt")
    setup.service.open_project.return_value.workspace = Workspace(LocalWorkspaceBackend(tmp_path))
    await setup.selector.select(uuid4())
    await setup.selector.read_file("alias.txt")
    (tmp_path / "actual.txt").write_text("someone else's edit")
    with pytest.raises(WorkspaceUnavailableError, match="changed since"):
        await setup.selector.write_file("actual.txt", "stale replacement")
    assert (tmp_path / "actual.txt").read_text() == "someone else's edit"


async def test_api_context_is_refreshed_without_borrowing_a_different_issuer(
    setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    setup.selector.ctx = replace(setup.ctx, api_key_id=uuid4())
    current = replace(setup.selector.ctx, key_scopes=frozenset({"projects:read"}))
    refresh = AsyncMock(return_value=current)
    monkeypatch.setattr(module, "ApiKeyService", lambda _: SimpleNamespace(context_for_key=refresh))
    await setup.selector.select(uuid4())
    refresh.assert_awaited_once()
    refresh.return_value = replace(current, user_id=uuid4())
    with pytest.raises(AuthorizationError, match="original issuer"):
        await setup.selector.select(uuid4())


async def test_project_search_returns_only_still_selectable_ids_without_opening_runtime(
    setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import project as project_module

    selected = setup.guard.return_value
    listing = AsyncMock(return_value=SimpleNamespace(items=[selected, selected]))
    monkeypatch.setattr(
        project_module, "ProjectService", lambda _: SimpleNamespace(list_projects=listing)
    )
    setup.guard.side_effect = [NotFoundError(message="gone"), selected]
    answer = await setup.selector.search("HN", 2)
    assert str(selected.id) in answer
    assert answer.count(str(selected.id)) == 1
    setup.service.open_project.assert_not_awaited()


async def test_checkpoint_initialization_requires_the_admitted_project(
    setup: SimpleNamespace,
) -> None:
    project = setup.guard.return_value
    with pytest.raises(ValueError, match="admitted"):
        setup.selector.initialize(project, execution_target="project")
    setup.selector.conversation_project_id = project.id
    setup.selector.initialize(project, execution_target="agent")
    assert setup.selector.project_id == project.id
    assert setup.selector.project_generation == project.workspace_generation
    setup.selector.restore(None, None, None)
    assert setup.selector.project_id == project.id
    setup.selector.restore(None, None, "agent")
    assert setup.selector.project_id is None


async def test_text_tools_require_selection_and_bound_writes(setup: SimpleNamespace) -> None:
    with pytest.raises(AuthorizationError, match="Select a project"):
        await setup.selector.read_file("notes.md")
    await setup.selector.select(uuid4())
    with pytest.raises(BadRequestError, match="too large"):
        await setup.selector.write_file("notes.md", "é" * 128_001)


@pytest.mark.parametrize("size", [None, 1])
async def test_unknown_size_and_growing_text_are_not_silently_read(
    setup: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, size: int | None
) -> None:
    await setup.project.write_text("note.txt", "bounded")
    await setup.selector.select(uuid4())
    monkeypatch.setattr(
        setup.project, "stat", AsyncMock(return_value=SimpleNamespace(is_dir=False, size=size))
    )
    if size is not None:
        monkeypatch.setattr(setup.project, "read_bytes", AsyncMock(return_value=b"x" * 256_001))
    with pytest.raises(BadRequestError):
        await setup.selector.read_file("note.txt")


async def test_absent_agent_executor_remains_explicit_and_can_not_run(
    setup: SimpleNamespace,
) -> None:
    selector = RunProjectWorkspace(
        None, setup.ctx, audience=RunAudience(user_id=setup.ctx.user_id), granted_scopes=frozenset()
    )
    with pytest.raises(WorkspaceUnavailableError, match="no workspace"):
        async with selector._open_agent():
            pytest.fail("missing executor yielded")
    with pytest.raises(WorkspaceUnavailableError, match="unavailable"):
        await selector.run(["true"])
    selector.agent_execution_available = True
    selector.open_agent_executor = AsyncMock(return_value=None)
    with pytest.raises(WorkspaceUnavailableError, match="no workspace"):
        async with selector._open_agent():
            pytest.fail("missing executor yielded")
    assert module._UnavailableWorkspace().ref is None
    with pytest.raises(WorkspaceUnavailableError):
        await module._UnavailableWorkspace().working_dir()


async def test_executor_selection_and_command_recheck_project_generation(
    setup: SimpleNamespace,
) -> None:
    with pytest.raises(AuthorizationError, match="Select a project"):
        await setup.selector.select_execution("project")
    setup.guard.return_value.backend = "service"
    await setup.selector.select(uuid4())
    setup.guard.return_value.workspace_generation = uuid4()
    with pytest.raises(module.ConcurrentChangeError, match="again"):
        await setup.selector.select_execution("project")
    setup.selector.agent_execution_available = True
    with pytest.raises(PermissionError, match="again"):
        await setup.selector.run(["true"])
    setup.selector.execution_target = "project"
    setup.selector.project_id = None
    with pytest.raises(WorkspaceUnavailableError, match="Select a project"):
        await setup.selector.run(["true"])


async def test_file_context_never_claims_disabled_shell_tools_are_available(
    setup: SimpleNamespace,
) -> None:
    setup.selector.shell_tools_enabled = False
    setup.guard.return_value.backend = "service"
    answer = await setup.selector.select(uuid4())
    assert '"project_execution_available": false' in answer
    with pytest.raises(AuthorizationError, match="no enabled Sandbox"):
        await setup.selector.select_execution("project")
    setup.service.open_project.assert_not_awaited()


async def test_project_origin_records_only_a_materialized_workspace(setup: SimpleNamespace) -> None:
    setup.service.open_project.return_value.row_id = uuid4()
    await setup.selector.select(uuid4())
    assert setup.selector.origins == {}
    await setup.selector.files()
    assert (
        setup.selector.origins[setup.service.open_project.return_value.row_id]["kind"] == "project"
    )


async def test_missing_paths_walk_only_inside_the_project_for_creation(
    setup: SimpleNamespace,
) -> None:
    workspace = SimpleNamespace(
        resolve=AsyncMock(return_value="/project/new/deeper.txt"),
        realpath=AsyncMock(side_effect=FileNotFoundError()),
        working_dir=AsyncMock(return_value="/project"),
    )
    with pytest.raises(FileNotFoundError):
        await RunProjectWorkspace._file_path(workspace, "new/deeper.txt")
    workspace.realpath.side_effect = [FileNotFoundError(), FileNotFoundError(), "/project"]
    assert (
        await RunProjectWorkspace._file_path(workspace, "new/deeper.txt", create=True)
        == "new/deeper.txt"
    )
    workspace.resolve.return_value = "/"
    workspace.realpath.side_effect = FileNotFoundError()
    with pytest.raises(FileNotFoundError):
        await RunProjectWorkspace._file_path(workspace, "file.txt", create=True)
    assert await RunProjectWorkspace._version_path(workspace, "missing.txt") == "/"


async def test_write_scope_refuses_directory_creation_and_removal(setup: SimpleNamespace) -> None:
    await setup.selector.select(uuid4())
    setup.selector.granted_scopes = frozenset({"projects:read"})
    for operation in (setup.selector.make_dir, setup.selector.remove):
        with pytest.raises(PermissionError, match="writes are disabled"):
            await operation("notes")


async def test_agent_command_without_project_uses_its_original_executor(
    setup: SimpleNamespace, tmp_path: Path
) -> None:
    from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

    setup.selector.original = Workspace(LocalWorkspaceBackend(tmp_path))
    setup.selector.agent_execution_available = True
    result = await setup.selector.run(["/bin/pwd"], timeout=5)
    assert result.stdout.strip() == str(tmp_path.resolve())


async def test_explicit_agent_target_and_files_only_checkpoint_do_not_forge_a_shell(
    setup: SimpleNamespace,
) -> None:
    setup.selector.agent_execution_available = True
    assert '"execution_target": "agent"' in await setup.selector.select_execution("agent")
    await setup.selector.select(uuid4())
    setup.selector.execution_target = "project"
    with pytest.raises(WorkspaceUnavailableError, match="files only"):
        await setup.selector.run(["true"])


async def test_executor_tool_is_sequential_and_returns_controlled_refusals() -> None:
    from app.agents.capabilities.sandbox._project import project_tools

    missing = project_tools(None).tools["select_execution_target"]
    assert missing.sequential
    assert "unavailable" in await missing.function("agent")
    port = SimpleNamespace(select_execution=AsyncMock(return_value="selected"))
    tool = project_tools(port).tools["select_execution_target"]
    assert await tool.function("project") == "selected"
    port.select_execution.assert_awaited_once_with("project")
    port.select_execution.side_effect = AuthorizationError(message="Project executor denied")
    assert await tool.function("project") == "Project executor denied"
