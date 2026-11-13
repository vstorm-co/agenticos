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
import anyio.lowlevel
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


async def test_a_grown_binary_at_the_revert_file_limit_restores_its_original_bytes(
    root: Path,
) -> None:
    changes = await captured(
        root, lambda path: (path / "one.txt").write_bytes(b"\x00" * (2 * 1024 * 1024))
    )
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "one.txt").read_text() == "before\n"


@pytest.mark.security
async def test_verification_byte_budget_also_bounds_old_stored_snapshots(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import _coding_task_revert

    def edit(path: Path) -> None:
        (path / "one.txt").write_text("after one\n")
        (path / "two.txt").write_text("after two\n")

    changes = await captured(root, edit)
    monkeypatch.setattr(_coding_task_revert, "MAX_REVERT_BYTES", 12)
    with pytest.raises(AlreadyExistsError) as refused:
        await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert refused.value.details == {"conflicting_files": ["two.txt"]}
    assert (root / "one.txt").read_text() == "after one\n"
    assert (root / "two.txt").read_text() == "after two\n"


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
        snapshot_isolated=True,
        revert_job_id=None,
        revert_started_at=None,
        revert_failure=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def facade(monkeypatch: pytest.MonkeyPatch, stored: CodingTaskChange) -> SimpleNamespace:
    conversations = SimpleNamespace(
        get_conversation=AsyncMock(return_value=SimpleNamespace(id=stored.conversation_id))
    )
    monkeypatch.setattr(service_module, "ConversationService", lambda db: conversations)
    repository = SimpleNamespace(
        get_in_organization=AsyncMock(return_value=stored), save=AsyncMock()
    )
    monkeypatch.setattr(service_module, "change_repo", repository)
    enqueue = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(service_module, "enqueue", enqueue)
    job = AsyncMock(return_value=None)
    monkeypatch.setattr(service_module.job_repo, "get", job)
    gate = AsyncMock(return_value=[])
    monkeypatch.setattr(
        service_module,
        "SandboxWorkspaceService",
        lambda db: SimpleNamespace(recorded_for_task=gate),
    )
    admission = AsyncMock()
    monkeypatch.setattr(service_module, "admit", admission)
    return SimpleNamespace(
        service=CodingTaskChangeService(MagicMock()),
        ctx=AuthContext(user_id=uuid4(), organization_id=stored.organization_id, role="viewer"),
        conversations=conversations,
        repository=repository,
        enqueue=enqueue,
        job=job,
        gate=gate,
        admission=admission,
    )


async def test_undo_reserves_a_durable_job_without_running_a_workspace_command(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    result = await facade.service.revert(facade.ctx, stored.id)
    assert (
        result.reverted_at is None and result.revert_status == "pending" and not result.can_revert
    )
    assert stored.revert_job_id == facade.enqueue.return_value
    assert "revert_patch" not in result.model_dump() and "workspace_ref" not in result.model_dump()
    task, payload = facade.enqueue.await_args.args[1:]
    assert task.kind == "revert-coding-task" and payload.user_id == facade.ctx.user_id
    assert payload.organization_id == stored.organization_id and payload.change_id == stored.id
    assert facade.enqueue.await_args.kwargs["dedupe_active"] is True
    assert facade.enqueue.await_args.kwargs["concurrency_key"] == (
        f"coding-task-revert:{stored.organization_id}"
    )
    assert facade.conversations.get_conversation.await_args.kwargs["for_write"] is True
    stored.reverted_at = datetime.now(UTC)
    again = await facade.service.revert(facade.ctx, stored.id)
    assert again.reverted_at == stored.reverted_at
    assert facade.enqueue.await_count == 1


@pytest.mark.security
async def test_queued_undo_preserves_api_key_authority_for_the_worker(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    key_id = uuid4()
    ctx = AuthContext(
        user_id=facade.ctx.user_id,
        organization_id=stored.organization_id,
        role="viewer",
        api_key_id=key_id,
    )
    await facade.service.revert(ctx, stored.id)
    assert facade.enqueue.await_args.args[2].api_key_id == key_id


@pytest.mark.parametrize("retained_job", [True, False])
async def test_a_person_can_retry_an_unknown_outcome_without_erasing_its_recovery_state(
    facade: SimpleNamespace, stored: CodingTaskChange, retained_job: bool
) -> None:
    old_job, started = uuid4(), datetime.now(UTC)
    stored.revert_job_id, stored.revert_started_at = old_job, started
    facade.job.return_value = SimpleNamespace(status="dead") if retained_job else None
    result = await facade.service.revert(facade.ctx, stored.id)
    assert result.revert_status == "pending"
    assert stored.revert_job_id != old_job and stored.revert_started_at == started


async def test_a_reservation_committed_after_the_reader_check_still_prevents_a_duplicate_job(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    observed = SimpleNamespace(
        **{key: value for key, value in stored.__dict__.items() if not key.startswith("_")}
    )
    stored.revert_job_id = uuid4()
    facade.repository.get_in_organization.side_effect = [observed, stored]
    facade.job.return_value = SimpleNamespace(status="queued")
    with pytest.raises(AlreadyExistsError):
        await facade.service.revert(facade.ctx, stored.id)
    facade.enqueue.assert_not_awaited()


@pytest.mark.security
async def test_a_reader_without_edit_access_cannot_queue_undo(
    facade: SimpleNamespace, stored: CodingTaskChange
) -> None:
    facade.conversations.get_conversation.side_effect = [
        SimpleNamespace(),
        NotFoundError(message="Missing", details={}),
    ]
    with pytest.raises(NotFoundError):
        await facade.service.revert(facade.ctx, stored.id)
    facade.enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "reason",
    [
        "truncated",
        "omitted",
        "legacy",
        "no-workspace",
        "shared",
        "deleted",
        "active",
        "duplicate",
        "deduped",
        "finished",
    ],
)
async def test_unsafe_or_duplicate_undo_requests_never_start_another_job(
    facade: SimpleNamespace, stored: CodingTaskChange, reason: str
) -> None:
    if reason in ("truncated", "omitted"):
        setattr(stored, reason, 1)
    elif reason == "legacy":
        stored.revert_patch = None
    elif reason == "no-workspace":
        stored.workspace_ref = None
    elif reason == "shared":
        stored.snapshot_isolated = False
    elif reason == "deleted":
        facade.repository.get_in_organization.side_effect = [stored, None]
    elif reason == "active":
        facade.admission.side_effect = AlreadyExistsError(message="Busy", details={})
    elif reason == "duplicate":
        stored.revert_job_id = uuid4()
        facade.job.return_value = SimpleNamespace(status="running")
    elif reason == "deduped":
        facade.enqueue.return_value = None
    elif reason == "finished":
        # Another worker can finish between the reader check and the row lock.
        finished = SimpleNamespace(
            **{key: value for key, value in stored.__dict__.items() if not key.startswith("_")}
        )
        finished.reverted_at = datetime.now(UTC)
        facade.repository.get_in_organization.side_effect = [stored, finished]
        result = await facade.service.revert(facade.ctx, stored.id)
        assert result.reverted_at is not None
        facade.enqueue.assert_not_awaited()
        return
    expected = (
        NotFoundError
        if reason == "deleted"
        else AlreadyExistsError
        if reason in ("active", "duplicate", "deduped")
        else BadRequestError
    )
    with pytest.raises(expected):
        await facade.service.revert(facade.ctx, stored.id)
    assert facade.enqueue.await_count == (1 if reason == "deduped" else 0)


@pytest.mark.parametrize(
    "state",
    [
        "ready",
        "denied",
        "legacy",
        "truncated",
        "reverted",
        "shared",
        "pending",
        "unknown",
        "missing-job",
        "failed",
        "bad-failure",
    ],
)
async def test_read_reports_undo_progress_and_only_offers_a_safe_action(
    facade: SimpleNamespace, stored: CodingTaskChange, state: str
) -> None:
    if state == "denied":
        facade.gate.side_effect = NotFoundError(message="Missing", details={})
    elif state == "legacy":
        stored.revert_patch = None
    elif state == "truncated":
        stored.truncated = True
    elif state == "reverted":
        stored.reverted_at = datetime.now(UTC)
    elif state == "shared":
        stored.snapshot_isolated = False
    elif state in ("pending", "unknown", "missing-job"):
        stored.revert_job_id = uuid4()
        facade.job.return_value = (
            None
            if state == "missing-job"
            else SimpleNamespace(status="queued" if state == "pending" else "dead")
        )
    elif state in ("failed", "bad-failure"):
        stored.revert_failure = {
            "conflicting_files": ["one.txt", 42] if state == "failed" else "not a list"
        }
    result = await facade.service.read(facade.ctx, stored.id)
    assert result.can_revert is (
        state in ("ready", "unknown", "missing-job", "failed", "bad-failure")
    )
    assert result.revert_status == (
        "unknown"
        if state in ("unknown", "missing-job")
        else "pending"
        if state == "pending"
        else "failed"
        if state in ("failed", "bad-failure")
        else None
    )
    assert result.revert_conflicting_files == (["one.txt"] if state == "failed" else [])


async def test_reconciliation_recognizes_restored_files_without_reversing_twice(root: Path) -> None:
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    workspace = Workspace(LocalWorkspaceBackend(root))
    await revert(workspace, changes.files, changes.revert_patch)
    await revert(workspace, changes.files, changes.revert_patch, reconcile=True)
    assert (root / "one.txt").read_text() == "before\n"


async def test_reconciliation_can_finish_an_attempt_that_never_changed_files(root: Path) -> None:
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    await revert(
        Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch, reconcile=True
    )
    assert (root / "one.txt").read_text() == "before\n"


@pytest.mark.security
async def test_an_uncertain_partial_state_is_not_mistaken_for_a_fresh_conflict(root: Path) -> None:
    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    (root / "one.txt").write_text("unknown third state\n")
    with pytest.raises(ExternalServiceError):
        await revert(
            Workspace(LocalWorkspaceBackend(root)),
            changes.files,
            changes.revert_patch,
            reconcile=True,
        )
    assert (root / "one.txt").read_text() == "unknown third state\n"


async def test_a_still_running_attempt_cannot_be_overlapped_by_reconciliation(root: Path) -> None:
    import fcntl

    changes = await captured(root, lambda path: (path / "one.txt").write_text("after\n"))
    (root / ".agenticos").mkdir()
    with (root / ".agenticos" / "task-revert.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(ExternalServiceError):
            await revert(
                Workspace(LocalWorkspaceBackend(root)),
                changes.files,
                changes.revert_patch,
                reconcile=True,
            )
    assert (root / "one.txt").read_text() == "after\n"


async def test_notebook_fallback_keeps_the_exact_unclipped_notebook_path() -> None:
    from app.agents.capabilities.coding_agent._harness import claude_report

    path = "/workspace/" + "a/" * 110 + "notebook.ipynb"
    report, _ = claude_report(
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "NotebookEdit",
                            "input": {"notebook_path": path},
                        }
                    ]
                },
            },
            {"type": "result", "subtype": "success", "result": "done"},
        ],
        access="edit",
        base_url=None,
    )
    assert report.files_changed == [path]


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch, stored: CodingTaskChange) -> SimpleNamespace:
    from app.worker.jobs import RevertCodingTask
    from app.worker.tasks import coding_tasks

    ctx = AuthContext(user_id=uuid4(), organization_id=stored.organization_id, role="viewer")
    payload = RevertCodingTask(
        organization_id=stored.organization_id,
        change_id=stored.id,
        user_id=ctx.user_id,
        claim_id=uuid4(),
    )
    stored.revert_job_id = uuid4()
    job = SimpleNamespace(payload={"claim_id": str(payload.claim_id)})
    db = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def transaction() -> AsyncGenerator[object]:
        yield db
        await db.commit()

    @asynccontextmanager
    async def opened(*args: object, **kwargs: object) -> AsyncGenerator[object]:
        yield SimpleNamespace()

    get = AsyncMock(return_value=stored)
    save = AsyncMock()

    async def mark(*args: object, **kwargs: object) -> CodingTaskChange:
        stored.reverted_at = datetime.now(UTC)
        stored.revert_job_id = None
        return stored

    monkeypatch.setattr(coding_tasks.change_repo, "get_in_organization", get)
    monkeypatch.setattr(coding_tasks.change_repo, "save", save)
    monkeypatch.setattr(coding_tasks.change_repo, "mark_reverted", mark)
    owned = AsyncMock(return_value=job)
    monkeypatch.setattr(coding_tasks.job_repo, "get_for_attempt", owned)
    authority = AsyncMock(return_value=ctx)
    monkeypatch.setattr(coding_tasks, "job_context", authority)
    conversations = SimpleNamespace(get_conversation=AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(coding_tasks, "ConversationService", lambda db: conversations)
    monkeypatch.setattr(service_module, "ConversationService", lambda db: conversations)
    monkeypatch.setattr(
        coding_tasks, "SandboxWorkspaceService", lambda db: SimpleNamespace(open_recorded=opened)
    )
    monkeypatch.setattr(coding_tasks, "get_worker_db_context", transaction)
    monkeypatch.setattr(coding_tasks, "current_attempt_number", lambda: 1)
    restore = AsyncMock()
    monkeypatch.setattr(coding_tasks._coding_task_revert, "revert", restore)
    audit = AsyncMock()
    monkeypatch.setattr(coding_tasks, "record_audit", audit)
    return SimpleNamespace(
        run=coding_tasks.revert_coding_task,
        payload=payload,
        db=db,
        get=get,
        owned=owned,
        authority=authority,
        conversations=conversations,
        restore=restore,
        audit=audit,
        save=save,
    )


async def test_worker_commits_its_reservation_before_restoring_and_audits_success_once(
    worker: SimpleNamespace, stored: CodingTaskChange
) -> None:
    async def restore(*args: object, **kwargs: object) -> None:
        assert stored.revert_started_at is not None
        assert worker.db.commit.await_count == 1
        assert kwargs["reconcile"] is False

    worker.restore.side_effect = restore
    await worker.run(worker.payload)
    assert stored.reverted_at is not None and stored.revert_job_id is None
    assert worker.audit.await_args.kwargs["details"]["file_count"] == 1
    await worker.run(worker.payload)
    assert worker.restore.await_count == worker.audit.await_count == 1


@pytest.mark.parametrize("failure", [AlreadyExistsError, BadRequestError, ExternalServiceError])
async def test_worker_releases_only_definite_refusals_and_keeps_uncertain_effects_reserved(
    worker: SimpleNamespace, stored: CodingTaskChange, failure: type[Exception]
) -> None:
    worker.restore.side_effect = failure(
        message="Refused", details={"conflicting_files": ["one.txt"]}
    )
    if failure is ExternalServiceError:
        with pytest.raises(ExternalServiceError):
            await worker.run(worker.payload)
        assert stored.revert_job_id is not None and stored.revert_started_at is not None
        assert stored.revert_failure is None
    else:
        await worker.run(worker.payload)
        assert stored.revert_job_id is None and stored.revert_started_at is None
        assert stored.revert_failure == {"conflicting_files": ["one.txt"]}
    worker.audit.assert_not_awaited()
    assert stored.reverted_at is None


async def test_a_retry_reconciles_an_unknown_effect_instead_of_blindly_reapplying(
    worker: SimpleNamespace, stored: CodingTaskChange
) -> None:
    stored.revert_started_at = datetime.now(UTC)
    await worker.run(worker.payload)
    assert worker.restore.await_args.kwargs["reconcile"] is True


@pytest.mark.security
async def test_the_worker_rebuilds_the_original_keys_current_scopes(
    worker: SimpleNamespace,
) -> None:
    key_id = uuid4()
    payload = worker.payload.model_copy(update={"api_key_id": key_id})
    await worker.run(payload)
    assert worker.authority.await_args.kwargs["api_key_id"] == key_id


@pytest.mark.security
@pytest.mark.parametrize(
    "reason",
    [
        "member-removed",
        "grant-revoked",
        "unisolated",
        "missing-workspace",
        "missing-patch",
        "truncated",
        "omitted",
    ],
)
async def test_a_job_rechecks_access_and_capture_safety_before_any_external_effect(
    worker: SimpleNamespace, stored: CodingTaskChange, reason: str
) -> None:
    from app.core.exceptions import AuthorizationError

    expected = BadRequestError
    if reason == "member-removed":
        worker.authority.return_value = None
        expected = AuthorizationError
    elif reason == "grant-revoked":
        worker.conversations.get_conversation.side_effect = NotFoundError(
            message="Missing", details={}
        )
        expected = NotFoundError
    elif reason == "unisolated":
        stored.snapshot_isolated = False
    elif reason == "missing-workspace":
        stored.workspace_ref = None
    elif reason == "missing-patch":
        stored.revert_patch = None
    else:
        setattr(stored, reason, 1)
    with pytest.raises(expected):
        await worker.run(worker.payload)
    worker.restore.assert_not_awaited()
    assert stored.revert_job_id is not None


@pytest.mark.security
@pytest.mark.parametrize(
    "reason",
    [
        "missing",
        "reverted",
        "no-job",
        "lease-lost",
        "superseded",
        "locked-missing",
        "locked-new-job",
        "locked-reverted",
        "lost-after-effect",
    ],
)
async def test_a_worker_without_the_current_fence_cannot_mutate_or_settle_the_task(
    worker: SimpleNamespace, stored: CodingTaskChange, reason: str
) -> None:
    if reason == "missing":
        worker.get.return_value = None
    elif reason == "reverted":
        stored.reverted_at = datetime.now(UTC)
    elif reason == "no-job":
        stored.revert_job_id = None
    elif reason == "lease-lost":
        worker.owned.return_value = None
    elif reason == "superseded":
        worker.owned.return_value = SimpleNamespace(payload={"claim_id": str(uuid4())})
    elif reason == "lost-after-effect":
        worker.owned.side_effect = [worker.owned.return_value, None]
    else:
        locked = SimpleNamespace(revert_job_id=stored.revert_job_id, reverted_at=None)
        if reason == "locked-new-job":
            locked.revert_job_id = uuid4()
        elif reason == "locked-reverted":
            locked.reverted_at = datetime.now(UTC)
        worker.get.side_effect = [stored, None if reason == "locked-missing" else locked]
    await worker.run(worker.payload)
    assert worker.restore.await_count == (1 if reason == "lost-after-effect" else 0)
    worker.audit.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("busy", ["admission", "run", "revert", "none"])
async def test_workspace_admission_never_waits_or_overlaps_an_active_writer(
    monkeypatch: pytest.MonkeyPatch, busy: str
) -> None:
    from app.services import workspace_turn_guard as guard

    lock = AsyncMock(return_value=busy != "admission")
    running = AsyncMock(return_value=busy == "run")
    pending = AsyncMock(return_value=busy == "revert")
    monkeypatch.setattr(guard, "try_hold_subject", lock)
    monkeypatch.setattr(guard.run_repo, "has_running_in_conversation", running)
    monkeypatch.setattr(guard.change_repo, "has_pending_revert", pending)
    run_id = uuid4()
    if busy != "none":
        with pytest.raises(AlreadyExistsError):
            await guard.admit(
                MagicMock(), organization_id=uuid4(), conversation_id=uuid4(), run_id=run_id
            )
    else:
        await guard.admit(
            MagicMock(), organization_id=uuid4(), conversation_id=uuid4(), run_id=run_id
        )
        assert running.await_args.kwargs["excluding"] == run_id
    if busy == "admission":
        running.assert_not_awaited()
        pending.assert_not_awaited()


@pytest.mark.security
async def test_a_parallel_file_tool_cannot_enter_the_capture_interval(root: Path) -> None:
    from app.agents.capabilities.sandbox._recording import RecordingWorkspace

    workspace = RecordingWorkspace(
        Workspace(LocalWorkspaceBackend(root)),
        db=MagicMock(),
        organization_id=uuid4(),
        session_key="conversation",
        agent_id=None,
        isolated_turn=True,
    )
    ctx = RunContext(deps=AgentDeps(), model=TestModel(), usage=RunUsage(), workspace=workspace)
    start, written = anyio.Event(), anyio.Event()

    async def another_tool() -> None:
        await start.wait()
        await workspace.write_bytes("two.txt", b"other tool's work\n")
        written.set()

    async with anyio.create_task_group() as group:
        group.start_soon(another_tool)
        async with workspace.task_snapshot():
            assert workspace.snapshot_isolated
            baseline = await _changes.begin(ctx)
            assert baseline is not None
            start.set()
            await anyio.lowlevel.checkpoint()
            assert not written.is_set()
            await workspace.write_bytes("one.txt", b"task change\n")
            changes = await _changes.finish(ctx, baseline)
            assert changes is not None and [file.path for file in changes.files] == ["one.txt"]
        assert not workspace.snapshot_isolated
    assert written.is_set() and (root / "two.txt").read_text() == "other tool's work\n"


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


@pytest.mark.security
async def test_manual_queue_retry_cannot_reuse_a_retired_attempt_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import background_jobs
    from app.worker.jobs import REVERT_CODING_TASK

    job = SimpleNamespace(kind=REVERT_CODING_TASK.kind, status="dead")
    monkeypatch.setattr(background_jobs.background_job_repo, "get", AsyncMock(return_value=job))
    requeue = AsyncMock()
    monkeypatch.setattr(background_jobs.background_job_repo, "requeue_dead", requeue)
    with pytest.raises(BadRequestError, match="Retry the revert from its conversation"):
        await background_jobs.BackgroundJobService(MagicMock()).retry(
            uuid4(), actor_user_id=uuid4()
        )
    requeue.assert_not_awaited()


@pytest.mark.parametrize(
    ("attributes", "before", "after"),
    [
        ("*.txt text eol=lf\n", b"before\r\n", b"after\r\n"),
        ("*.txt text eol=crlf\n", b"before\n", b"after\n"),
        (
            "*.txt working-tree-encoding=UTF-16LE\n",
            "before\n".encode("utf-16le"),
            "after\n".encode("utf-16le"),
        ),
        ("*.txt ident\n", b"$Id: before $\nbefore\n", b"$Id: after $\nafter\n"),
    ],
)
async def test_attributes_cannot_transform_task_snapshot_or_restored_bytes(
    root: Path, attributes: str, before: bytes, after: bytes
) -> None:
    (root / ".gitattributes").write_text(attributes)
    (root / "one.txt").write_bytes(before)
    # Keep every text file valid for the encoding case.
    (root / "two.txt").unlink()
    changes = await captured(root, lambda path: (path / "one.txt").write_bytes(after))
    await revert(Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch)
    assert (root / "one.txt").read_bytes() == before
    await revert(
        Workspace(LocalWorkspaceBackend(root)), changes.files, changes.revert_patch, reconcile=True
    )
    assert (root / "one.txt").read_bytes() == before
