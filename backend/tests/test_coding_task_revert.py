"""Undo restores a task's exact files and refuses to overwrite later work (#2743)."""

import base64
import shutil
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import anyio
import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

from app.agents.capabilities.coding_agent import _changes
from app.agents.deps import AgentDeps
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.coding_task_change import CodingTaskChange
from app.schemas.coding_task_change import ChangeSet
from app.services import coding_task_changes as service_module
from app.services._coding_task_revert import manifests, revert
from app.services.coding_task_changes import CodingTaskChangeService

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("git") is None, reason="needs git"),
]


async def captured(root: Path, edit: Callable[[Path], None]) -> ChangeSet:
    workspace = Workspace(LocalWorkspaceBackend(root))
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), workspace=workspace)
    baseline = await _changes.begin(ctx)
    assert baseline is not None
    edit(root)
    changes = await _changes.finish(ctx, baseline)
    assert changes is not None and changes.revert_patch
    return changes


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(_changes, "CHANGES_ROOT", str(tmp_path / "snapshots"))
    directory = tmp_path / "workspace"
    directory.mkdir()
    (directory / "one.txt").write_text("before\n")
    (directory / "two.txt").write_text("before two\n")
    return directory


async def test_two_edits_and_an_added_file_return_to_the_exact_before_state(root: Path) -> None:
    def edit(path: Path) -> None:
        (path / "one.txt").write_text("after\n")
        (path / "two.txt").write_text("after two\n")
        (path / "new.txt").write_text("created\n")

    changes = await captured(root, edit)
    (root / "unrelated.txt").write_text("a later unrelated edit\n")

    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)

    assert (root / "one.txt").read_text() == "before\n"
    assert (root / "two.txt").read_text() == "before two\n"
    assert not (root / "new.txt").exists()
    assert (root / "unrelated.txt").read_text() == "a later unrelated edit\n"


async def test_a_task_that_only_deletes_a_file_can_be_restored(root: Path) -> None:
    changes = await captured(root, lambda path: (path / "one.txt").unlink())
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "one.txt").read_text() == "before\n"


@pytest.mark.security
async def test_workspace_python_modules_cannot_run_during_revert(root: Path) -> None:
    (root / "json.py").write_text("raise RuntimeError('workspace code executed')\n")
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "one.txt").read_text() == "before\n"


async def test_a_large_complete_patch_is_sent_below_linuxs_per_value_environment_limit(
    root: Path,
) -> None:
    original = "".join(f"old {index} {'a' * 150}\n" for index in range(400))
    (root / "one.txt").write_text(original)
    changes = await captured(
        root, lambda path: (path / "one.txt").write_text(original.replace("old", "new"))
    )
    assert len(changes.revert_patch) > 128 * 1024
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "one.txt").read_text() == original


async def test_executable_mode_and_quoted_unicode_paths_are_restored(root: Path) -> None:
    file = root / 'zażółć "name".sh'
    file.write_text("echo before\n")
    file.chmod(0o755)

    def edit(path: Path) -> None:
        changed = path / file.name
        changed.write_text("echo after\n")
        changed.chmod(0o644)

    changes = await captured(root, edit)
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert file.read_text() == "echo before\n"
    assert file.stat().st_mode & 0o111


def test_harness_fallback_paths_are_relative_to_the_workspace() -> None:
    from app.agents.capabilities.coding_agent._harness import CodingReport
    from app.agents.capabilities.coding_agent._toolset import _relative_files

    report = CodingReport(
        harness="codex",
        access="edit",
        outcome="completed",
        answer="done",
        files_changed=[
            "/workspace/src/a.py",
            "./src/b.py",
            "/elsewhere/secret",
            "../outside",
            "src/a.py",
        ],
    )
    assert _relative_files(report, "/workspace/").files_changed == ["src/a.py", "src/b.py"]


async def test_a_lost_workspace_does_not_replace_the_completed_tasks_answer_with_a_path_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pydantic_ai.workspaces import WorkspaceUnavailableError

    from app.agents.capabilities.coding_agent._harness import CodingReport
    from app.agents.capabilities.coding_agent._toolset import _relative_report

    report = CodingReport(
        harness="codex",
        access="edit",
        outcome="completed",
        answer="The task finished.",
        files_changed=["/workspace/a.py"],
    )
    workspace = SimpleNamespace(
        working_dir=AsyncMock(side_effect=WorkspaceUnavailableError("PRIVATE PATH"))
    )
    result = await _relative_report(workspace, report)
    assert result.answer == report.answer and result.outcome == "completed"
    assert result.files_changed == []
    assert "PRIVATE PATH" not in caplog.text


async def test_renames_deletions_empty_and_binary_files_are_restored_losslessly(root: Path) -> None:
    binary = b"\0\xff\x89PNG\n"
    (root / "binary.bin").write_bytes(binary)
    (root / "latin.txt").write_bytes(b"ol\xe1\n")

    def edit(path: Path) -> None:
        (path / "one.txt").rename(path / "renamed.txt")
        (path / "two.txt").unlink()
        (path / "binary.bin").write_bytes(b"\0new binary\xff\n")
        (path / "latin.txt").write_bytes(b"caff\xe8\n")
        (path / "empty.txt").touch()

    changes = await captured(root, edit)

    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)

    assert (root / "one.txt").read_text() == "before\n"
    assert (root / "two.txt").read_text() == "before two\n"
    assert (root / "binary.bin").read_bytes() == binary
    assert (root / "latin.txt").read_bytes() == b"ol\xe1\n"
    assert not (root / "renamed.txt").exists()
    assert not (root / "empty.txt").exists()


@pytest.mark.security
async def test_a_later_edit_outside_the_patch_hunk_refuses_the_whole_revert(root: Path) -> None:
    original = "".join(f"line {index}\n" for index in range(100))
    (root / "one.txt").write_text(original)

    def edit(path: Path) -> None:
        (path / "one.txt").write_text(original.replace("line 1\n", "task change\n"))
        (path / "two.txt").write_text("task change two\n")

    changes = await captured(root, edit)
    later = (root / "one.txt").read_text().replace("line 90\n", "later edit\n")
    (root / "one.txt").write_text(later)

    with pytest.raises(AlreadyExistsError) as refused:
        await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)

    assert refused.value.details == {"conflicting_files": ["one.txt"]}
    assert (root / "one.txt").read_text() == later
    assert (root / "two.txt").read_text() == "task change two\n"


@pytest.mark.security
async def test_an_extra_patch_path_is_refused_before_any_file_changes(root: Path) -> None:
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    patch = base64.b64decode(changes.revert_patch)
    forged = (
        patch
        + b"diff --git a/extra.txt b/extra.txt\ndeleted file mode 100644\n--- a/extra.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n+forged\n"
    )
    with pytest.raises(BadRequestError):
        await revert(
            Workspace(LocalWorkspaceBackend(root)), changes.files, base64.b64encode(forged).decode()
        )
    assert (root / "one.txt").read_text() == "after\n"
    assert not (root / "extra.txt").exists()


async def test_a_nested_repository_keeps_its_head_and_index(root: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    await anyio.run_process([git, "init", "-q", str(root)])
    await anyio.run_process([git, "-C", str(root), "add", "one.txt"])
    index = (root / ".git" / "index").read_bytes()
    head = (root / ".git" / "HEAD").read_bytes()
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))

    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)

    assert (root / "one.txt").read_text() == "before\n"
    assert (root / ".git" / "index").read_bytes() == index
    assert (root / ".git" / "HEAD").read_bytes() == head


@pytest.mark.security
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "missing", "directory"])
async def test_a_replaced_file_is_a_conflict_and_no_other_file_is_restored(
    root: Path, kind: str
) -> None:
    def edit(path: Path) -> None:
        (path / "one.txt").write_text("after\n")
        (path / "two.txt").write_text("after two\n")

    changes = await captured(root, edit)
    file = root / "one.txt"
    if kind == "mode":
        file.chmod(0o755)
    else:
        file.unlink()
        if kind == "symlink":
            file.symlink_to(root / "two.txt")
        elif kind == "hardlink":
            file.hardlink_to(root / "two.txt")
        elif kind == "directory":
            file.mkdir()
    with pytest.raises(AlreadyExistsError):
        await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "two.txt").read_text() == "after two\n"


@pytest.mark.security
async def test_a_symlink_parent_cannot_redirect_undo_outside_the_workspace(root: Path) -> None:
    folder = root / "src"
    folder.mkdir()
    (folder / "app.py").write_text("before\n")
    changes = await captured(root, lambda path: (path / "src" / "app.py").write_text("after\n"))
    outside = root.parent / "outside"
    folder.rename(outside)
    folder.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AlreadyExistsError):
        await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (outside / "app.py").read_text() == "after\n"


@pytest.mark.security
@pytest.mark.parametrize(
    "path",
    ["../outside", "/outside", "a/../outside", "./a", ".git/config", "tool_output/x", "", "a\0b"],
)
async def test_an_unsafe_recorded_path_never_reaches_the_workspace(root: Path, path: str) -> None:
    changes = await captured(root, lambda directory: (directory / "one.txt").write_text("after\n"))
    changed = changes.files[0].model_copy(update={"path": path})
    workspace = MagicMock()
    with pytest.raises(BadRequestError):
        await revert(workspace, [changed], changes.revert_patch)
    workspace.run.assert_not_called()


@pytest.mark.parametrize(
    "status", ["invalid_patch", "unavailable", "broken-json", "nonzero", "raised"]
)
async def test_a_failed_restore_reports_the_failure_without_exposing_its_output(
    root: Path, status: str
) -> None:
    from pydantic_ai.workspaces import CommandResult, WorkspaceError

    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    workspace = SimpleNamespace(run=AsyncMock())
    workspace.run.return_value = CommandResult(
        exit_code=1 if status == "nonzero" else 0,
        stdout="PRIVATE"
        if status == "broken-json"
        else '{"status":"' + ("ok" if status == "nonzero" else status) + '"}',
        stderr="PRIVATE",
    )
    if status == "raised":
        workspace.run.side_effect = WorkspaceError("PRIVATE")
    with pytest.raises(
        BadRequestError if status == "invalid_patch" else ExternalServiceError
    ) as refused:
        await revert(workspace, changes.files, changes.revert_patch)
    assert "PRIVATE" not in refused.value.message


def test_older_link_and_duplicate_snapshots_cannot_offer_revert() -> None:
    from app.schemas.coding_task_change import ChangedFile

    legacy = ChangedFile(path="one.txt", status="modified")
    with pytest.raises(BadRequestError):
        manifests([legacy])
    file = legacy.model_copy(
        update={
            "before_blob": "a" * 40,
            "after_blob": "b" * 40,
            "before_mode": "100644",
            "after_mode": "100644",
        }
    )
    with pytest.raises(BadRequestError):
        manifests([file, file])
    with pytest.raises(BadRequestError):
        manifests([file.model_copy(update={"after_mode": "120000"})])


@pytest.fixture
def stored() -> CodingTaskChange:
    from app.schemas.coding_task_change import ChangedFile

    file = ChangedFile(
        path="one.txt",
        status="modified",
        before_blob="a" * 40,
        after_blob="b" * 40,
        before_mode="100644",
        after_mode="100644",
        patch="patch",
    )
    return CodingTaskChange(
        id=uuid4(),
        organization_id=uuid4(),
        conversation_id=uuid4(),
        harness="codex",
        files=[file.model_dump()],
        omitted=0,
        truncated=False,
        revert_patch="cGF0Y2g=",
        workspace_ref={"provider": "sandboxd:host", "id": "session"},
        reverted_at=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def facade(monkeypatch: pytest.MonkeyPatch, stored: CodingTaskChange) -> SimpleNamespace:
    conversations = SimpleNamespace(
        get_conversation=AsyncMock(return_value=SimpleNamespace(project_id=None))
    )
    monkeypatch.setattr(service_module, "ConversationService", lambda db: conversations)
    repository = SimpleNamespace(
        get_in_organization=AsyncMock(return_value=stored), mark_reverted=AsyncMock()
    )
    monkeypatch.setattr(service_module, "change_repo", repository)
    audit = AsyncMock()
    monkeypatch.setattr(service_module, "record_audit", audit)
    running = AsyncMock(return_value=False)
    monkeypatch.setattr(service_module.run_repo, "has_running_in_conversation", running)
    gate = MagicMock()

    @asynccontextmanager
    async def opened(*args: object, **kwargs: object) -> AsyncGenerator[object]:
        gate(*args, **kwargs)
        yield SimpleNamespace()

    async def recorded(*args: object, **kwargs: object) -> list[object]:
        gate(*args, **kwargs)
        return [SimpleNamespace()]

    monkeypatch.setattr(
        service_module,
        "SandboxWorkspaceService",
        lambda db: SimpleNamespace(open_recorded=opened, recorded_for_task=recorded),
    )
    restore = AsyncMock()
    monkeypatch.setattr(service_module._coding_task_revert, "revert", restore)

    async def mark(*args: object, **kwargs: object) -> CodingTaskChange:
        stored.reverted_at = datetime.now(UTC)
        return stored

    repository.mark_reverted.side_effect = mark
    return SimpleNamespace(
        service=CodingTaskChangeService(MagicMock()),
        ctx=AuthContext(user_id=uuid4(), organization_id=stored.organization_id, role="viewer"),
        conversations=conversations,
        repository=repository,
        audit=audit,
        running=running,
        gate=gate,
        restore=restore,
    )


async def test_an_authorized_revert_is_audited_once_and_retries_are_idempotent(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    result = await facade.service.revert(facade.ctx, stored.id)
    assert result.reverted_at is not None and not result.can_revert
    assert "revert_patch" not in result.model_dump()
    assert "workspace_ref" not in result.model_dump()
    assert facade.restore.await_count == 1
    assert facade.audit.await_args.kwargs["details"] == {
        "conversation_id": str(stored.conversation_id),
        "file_count": 1,
    }
    assert facade.conversations.get_conversation.await_args.kwargs["for_write"] is True
    assert facade.repository.get_in_organization.await_args.kwargs["for_update"] is True
    again = await facade.service.revert(facade.ctx, stored.id)
    assert again.reverted_at == result.reverted_at
    assert facade.restore.await_count == facade.audit.await_count == 1


@pytest.mark.security
async def test_a_reader_without_edit_access_cannot_revert(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    facade.conversations.get_conversation.side_effect = [
        SimpleNamespace(),
        NotFoundError(message="Conversation not found", details={}),
    ]
    with pytest.raises(NotFoundError):
        await facade.service.revert(facade.ctx, stored.id)
    facade.restore.assert_not_awaited()
    facade.audit.assert_not_awaited()


@pytest.mark.parametrize(
    "reason", ["truncated", "omitted", "legacy", "no-workspace", "active", "deleted"]
)
async def test_an_incomplete_or_active_task_never_reaches_restore(
    facade: SimpleNamespace, stored: CodingTaskChange, reason: str
) -> None:
    if reason in ("truncated", "omitted"):
        setattr(stored, reason, True if reason == "truncated" else 1)
    elif reason == "legacy":
        stored.revert_patch = None
    elif reason == "no-workspace":
        stored.workspace_ref = None
    elif reason == "active":
        facade.running.return_value = True
    elif reason == "deleted":
        facade.repository.get_in_organization.side_effect = [stored, None]
    expected = (
        AlreadyExistsError
        if reason == "active"
        else NotFoundError
        if reason == "deleted"
        else BadRequestError
    )
    with pytest.raises(expected):
        await facade.service.revert(facade.ctx, stored.id)
    facade.restore.assert_not_awaited()
    facade.audit.assert_not_awaited()


@pytest.mark.parametrize("available", [True, False, "legacy", "truncated", "reverted", "moving"])
async def test_the_read_response_only_offers_revert_with_current_edit_access(
    facade: SimpleNamespace, stored: CodingTaskChange, available: bool | str
) -> None:
    if available is False:
        facade.gate.side_effect = NotFoundError(message="Conversation not found", details={})
    elif available == "legacy":
        stored.revert_patch = None
    elif available == "truncated":
        stored.truncated = True
    elif available == "reverted":
        stored.reverted_at = datetime.now(UTC)
    elif available == "moving":
        facade.gate.side_effect = AlreadyExistsError(message="Files are moving", details={})
    result = await facade.service.read(facade.ctx, stored.id)
    assert result.can_revert is (available is True)
    facade.restore.assert_not_awaited()


async def test_project_revert_takes_the_project_lock_before_locking_the_task(
    facade: SimpleNamespace, stored: CodingTaskChange, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = uuid4()
    facade.conversations.get_conversation.return_value = SimpleNamespace(project_id=project_id)
    order: list[str] = []

    async def project(*args: object) -> None:
        order.append("project")

    async def task(*args: object, **kwargs: object) -> CodingTaskChange:
        if kwargs.get("for_update"):
            order.append("task")
        return stored

    monkeypatch.setattr(service_module, "project_for_workspace", project)
    facade.repository.get_in_organization.side_effect = task
    await facade.service.revert(facade.ctx, stored.id)
    assert order == ["project", "task"]


@pytest.mark.security
@pytest.mark.parametrize("binary", [False, True])
async def test_personal_credentials_are_removed_from_the_display_and_lossless_patch(
    root: Path, binary: bool
) -> None:
    from app.agents.capabilities.coding_agent._redaction import redact_changes, redact_text

    secret = "private-token-never-store"
    data = (b"\0" if binary else b"") + secret.encode()
    changes = await captured(root, lambda path: (path / "credential.txt").write_bytes(data))
    redacted = redact_changes(changes, ("", secret))
    assert redacted.truncated and redacted.revert_patch is None
    assert redacted.files[0].patch is None
    assert secret not in redacted.model_dump_json()
    assert redact_text(secret, ("", secret)) == "[redacted]"
