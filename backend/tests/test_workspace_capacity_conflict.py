"""Concurrent accepted snapshots remain recoverable without growing the shared document."""

import errno
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai_backends import StateBackend

from app.agents.capabilities.sandbox._capped import CappedStateBackend, document_size
from app.core.exceptions import WorkspaceCapacityError
from app.services import sandbox_workspace as service
from tests.test_sandbox_workspace import _ctx, _identity, _row, _spec

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_the_losing_snapshot_is_committed_with_the_same_tenant_and_parent_scope(monkeypatch):
    monkeypatch.setattr(service.settings, "SANDBOX_STATE_MAX_BYTES", 1200)
    row = _row(version=1, owner_ref="person", conversation_id=uuid4(), project_id=uuid4())
    recovery = _row(scope_key=f"recovery-{uuid4().hex}")
    db, recovery_db = MagicMock(), MagicMock()
    db.get = AsyncMock(return_value=row)
    monkeypatch.setattr(service.workspace_repo, "get_by_key", AsyncMock(return_value=row))
    monkeypatch.setattr(service.workspace_repo, "touch", AsyncMock(return_value=row))
    created, saved = AsyncMock(return_value=recovery), AsyncMock(return_value=recovery)
    monkeypatch.setattr(service.workspace_repo, "create", created)
    monkeypatch.setattr(service.workspace_repo, "save_files", saved)
    committed = []

    @asynccontextmanager
    async def context():
        yield recovery_db
        committed.append(True)

    monkeypatch.setattr(service, "get_worker_db_context", context)
    workspace_service = service.SandboxWorkspaceService(db)
    opened = await workspace_service.open(_spec(), ctx=_ctx(), identity=_identity())
    assert opened is not None and opened.document is not None
    opened.document.write_bytes("/mine/file.txt", b"a" * 600)
    opened.document.make_dir("/mine/empty")
    theirs = StateBackend()
    theirs.write_bytes("/theirs/file.txt", b"b" * 600)
    theirs.make_dir("/theirs/empty")
    row.files, row.directories, row.version = dict(theirs.files), sorted(theirs.directories), 2
    before = dict(row.files)

    result = await workspace_service.close(opened)
    assert isinstance(result, service.WorkspaceFlushFailure)
    assert isinstance(result.error, WorkspaceCapacityError)
    assert result.error.details == {"recovery_workspace_id": str(recovery.id)}
    assert str(recovery.id) in result.error.message
    assert committed == [True]
    assert row.files == before
    saved.assert_awaited_once()
    written = saved.await_args.kwargs
    assert saved.await_args.args == (recovery_db,)
    assert written["workspace"] is recovery
    assert set(written["files"]) == {"/mine/file.txt"}
    assert "/mine/empty" in written["directories"]
    assert written["bytes_total"] == document_size(written["files"], written["directories"]) <= 1200
    ownership = created.await_args.kwargs
    for field in (
        "organization_id",
        "agent_id",
        "project_id",
        "conversation_id",
        "owner_ref",
        "scope",
    ):
        assert ownership[field] == getattr(row, field)
    assert ownership["scope_key"].startswith("recovery-")
    assert ownership["recovery_of_id"] == row.id


def test_empty_directories_cannot_bypass_the_storage_ceiling():
    document = CappedStateBackend(max_bytes=120)
    document.make_dir("/kept")
    before = set(document.directories)
    with pytest.raises(OSError) as refused:
        document.make_dir("/" + "/".join("a" * 15 for _ in range(20)))
    assert refused.value.errno == errno.ENOSPC
    assert document.directories == before
    assert document.stored_size() <= 120


async def test_a_failed_recovery_is_visible_instead_of_reported_as_saved(monkeypatch):
    workspace_service = service.SandboxWorkspaceService(MagicMock())
    opened = MagicMock(kind="state", scope_key="key")
    monkeypatch.setattr(
        workspace_service,
        "_flush_state",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    result = await workspace_service.close(opened)
    assert isinstance(result, service.WorkspaceFlushFailure)
    assert result.error.code == "EXTERNAL_SERVICE_ERROR"
    assert "could not be saved" in result.error.message


@pytest.mark.parametrize(
    "status_name", ["COMPLETED", "AWAITING_APPROVAL", "AWAITING_ANSWER", "CANCELLED"]
)
async def test_run_completion_records_the_conflict_and_preserves_primary_failures(
    monkeypatch, status_name
):
    from app.db.models.agent_run import RunStatus
    from app.services import agent_runner
    from tests.test_agent_runner import _db, _prepared

    runner, prepared = agent_runner.AgentRunnerService(_db()), _prepared()
    conflict = service.WorkspaceFlushFailure(
        WorkspaceCapacityError(message="Files preserved in recovery workspace")
    )
    monkeypatch.setattr(runner.workspaces, "close", AsyncMock(return_value=conflict))
    pending_id, standing_id = uuid4(), uuid4()
    prepared.approvals.requested = [
        agent_runner.ParkedApproval(
            approval_id=approval_id,
            tool_call_id=str(approval_id),
            tool_name="execute",
            tool_args={},
            standing=standing,
        )
        for approval_id, standing in ((pending_id, False), (standing_id, True))
    ]
    request = AsyncMock()
    monkeypatch.setattr(runner.approvals, "request", request)
    monkeypatch.setattr(
        agent_runner.agent_repo, "existing_ids_locked", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(runner, "_record_manifest", AsyncMock())
    monkeypatch.setattr(runner, "_notify", AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(agent_runner.agent_run_repo, "finish_run", finish)
    status = getattr(RunStatus, status_name)
    await runner.finish(
        prepared, status=status, error="Original error" if status_name == "CANCELLED" else None
    )
    fields = finish.await_args.kwargs
    assert fields["status"] == (
        status.value if status_name == "CANCELLED" else RunStatus.FAILED.value
    )
    assert "Files preserved" in fields["error"]
    assert ("Original error" in fields["error"]) == (status_name == "CANCELLED")
    assert fields["paused_state"] is None
    request.assert_awaited_once()
    assert request.await_args.kwargs["approval_id"] == standing_id
    assert (
        request.await_args.kwargs["standing_consent_by"] is prepared.approvals.standing_consent_by
    )


@pytest.mark.parametrize("operation", ["file", "folder", "remove"])
async def test_project_mutations_report_the_recovery_conflict(operation):
    from app.services.project import ProjectService

    project_service = ProjectService(MagicMock())
    project = MagicMock()
    project_service.get = AsyncMock(return_value=project)
    opened = MagicMock(kind="state")
    opened.workspace.make_dir = AsyncMock()
    opened.workspace.write_bytes = AsyncMock()
    opened.workspace.remove = AsyncMock()
    project_service.workspaces.open_project = AsyncMock(return_value=opened)
    project_service.workspaces.close = AsyncMock(
        return_value=service.WorkspaceFlushFailure(
            WorkspaceCapacityError(message="Files preserved in recovery workspace")
        )
    )
    project_service._touched = AsyncMock()
    with pytest.raises(WorkspaceCapacityError, match="Files preserved"):
        if operation == "file":
            await project_service.add_file(_ctx(), uuid4(), path="result.txt", data=b"data")
        elif operation == "folder":
            await project_service.add_folder(_ctx(), uuid4(), path="folder")
        else:
            await project_service.remove(_ctx(), uuid4(), path="result.txt")
    project_service._touched.assert_not_awaited()


@pytest.mark.parametrize(
    "view,use,exists",
    [(True, True, True), (False, True, True), (True, False, True), (True, True, False)],
)
async def test_project_recovery_downloads_require_both_project_permissions(
    monkeypatch, view, use, exists
):
    row = _row(project_id=uuid4(), scope_key="recovery-copy", recovery_of_id=uuid4())
    project = MagicMock()
    monkeypatch.setattr(
        service.project_repo, "get", AsyncMock(return_value=project if exists else None)
    )
    access = AsyncMock(side_effect=[view, use])
    monkeypatch.setattr(service, "resolve_access", access)
    assert await service.SandboxWorkspaceService(MagicMock())._may_read(_ctx(), row) is (
        view and use and exists
    )


async def test_only_authorized_project_recovery_copies_are_discoverable(monkeypatch):
    one, two = (
        _row(agent_id=None, project_id=uuid4(), scope_key="recovery-one", recovery_of_id=uuid4()),
        _row(agent_id=None, project_id=uuid4(), scope_key="recovery-two", recovery_of_id=uuid4()),
    )
    monkeypatch.setattr(service.workspace_repo, "list_for_reader", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        service.workspace_repo, "project_recovery_candidates", AsyncMock(return_value=[one, two])
    )
    projects = [MagicMock(id=one.project_id), MagicMock(id=two.project_id)]
    monkeypatch.setattr(service.project_repo, "get_many", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        service,
        "accessible_ids",
        AsyncMock(side_effect=[{one.project_id, two.project_id}, {one.project_id}]),
    )
    monkeypatch.setattr(service.agent_repo, "get_many", AsyncMock(return_value={}))
    monkeypatch.setattr(service.conversation_repo, "titles_for", AsyncMock(return_value={}))
    workspace_service = service.SandboxWorkspaceService(MagicMock())
    monkeypatch.setattr(workspace_service, "_owner_names", AsyncMock(return_value={}))
    [overview] = await workspace_service.visible_to(_ctx())
    assert overview.row is one
    assert overview.agent_name == "Project files (recovery copy)"


async def test_a_recovery_snapshot_cannot_bypass_its_own_cap(monkeypatch):
    monkeypatch.setattr(service.settings, "SANDBOX_STATE_MAX_BYTES", 100)
    document = StateBackend()
    document.write_bytes("/large.txt", b"x" * 200)
    with pytest.raises(RuntimeError, match="storage limit"):
        await service.SandboxWorkspaceService._recover_state(
            _row(), dict(document.files), sorted(document.directories)
        )


async def test_chat_commits_a_workspace_failure_before_reporting_it():
    from app.core.exceptions import RunFailedError
    from app.db.models.agent_run import RunStatus
    from tests.test_agent_chat import _db, _prepared, _run, _runner

    db, prepared = _db(), _prepared()

    async def fail_workspace(*args, **kwargs):
        prepared.run.status = RunStatus.FAILED.value
        prepared.run.error = "Files preserved in recovery workspace"

    with _runner(prepared) as runner:
        runner.finish.side_effect = fail_workspace
        with pytest.raises(RunFailedError, match="Files preserved"):
            await _run(db)
        assert runner.keep_plan.await_args.kwargs["status"] is RunStatus.FAILED
    assert db.commit.await_count == 2


async def test_recovery_metadata_and_project_batches_are_tenant_scoped():
    from sqlalchemy.dialects import postgresql

    from tests.test_agent_workspace_repo import _RecordingSession, _scalars

    organization, project_id = uuid4(), uuid4()
    db = _RecordingSession(_scalars([]), _scalars([]))
    assert (
        await service.workspace_repo.project_recovery_candidates(db, organization_id=organization)
        == []
    )
    assert await service.project_repo.get_many(db, [], organization_id=organization) == []
    assert await service.project_repo.get_many(db, [project_id], organization_id=organization) == []
    assert len(db.statements) == 2
    for statement in db.statements:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert organization in compiled.params.values()
    assert "project_id IS NOT NULL" in str(db.statements[0])
    assert "recovery_of_id IS NOT NULL" in str(db.statements[0])
