"""A transfer publishes only verified files, never the work of an expired attempt."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import FileEntry, Workspace, WorkspaceRef
from pydantic_ai_backends.workspaces import StateWorkspaceBackend
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.sandbox._capped import CappedStateBackend
from app.core.exceptions import (
    AlreadyExistsError,
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
)
from app.core.permissions import AuthContext
from app.db.models.background_job import BackgroundJob
from app.db.models.project import Project
from app.schemas.project import ProjectWorkspaceMoveRequest
from app.services import project_workspace_guard as guard
from app.services import project_workspace_transfer as module
from app.services.project_workspace_transfer import ProjectWorkspaceTransferService, manifest
from app.worker.attempt import Attempt, current_attempt_number, running
from app.worker.jobs import (
    MOVE_PROJECT_WORKSPACE,
    MoveProjectWorkspacePayload,
    project_move_generation,
)

pytestmark = pytest.mark.anyio


def workspace() -> Workspace:
    document = CappedStateBackend({}, (), max_bytes=10_000_000)
    return Workspace(
        StateWorkspaceBackend({"k": document}, ref=WorkspaceRef(provider="state", id="k"))
    )


@pytest.fixture
async def transfer(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    project = Project(
        id=uuid4(),
        organization_id=ctx.organization_id,
        backend="state",
        sandbox_connection_id=None,
        workspace_generation=None,
        workspace_move_job_id=uuid4(),
    )
    payload = MoveProjectWorkspacePayload(
        transfer_id=uuid4(),
        project_id=project.id,
        organization_id=ctx.organization_id,
        user_id=ctx.subject_id,
        source_backend="state",
        source_connection_id=None,
        source_generation=None,
        source_workspace_id=uuid4(),
        target_backend="service",
        target_connection_id=uuid4(),
        target_runtime=None,
        target_name="Cloud",
    )
    job = BackgroundJob(
        id=project.workspace_move_job_id,
        status="running",
        attempts=1,
        max_attempts=3,
        payload=MOVE_PROJECT_WORKSPACE.dump(payload),
        result={},
    )
    source, target = workspace(), workspace()
    await source.make_dir("notes/empty")
    await source.write_bytes("notes/data.bin", b"\x00\xffbinary")
    await source.write_text("notes/a.md", "  # Wiki\n")
    await source.write_text(".agenticos/private", "internal")
    await source.write_text("node_modules/installed-package.js", "installed")
    opened = [
        SimpleNamespace(workspace=source, row_id=payload.source_workspace_id),
        SimpleNamespace(workspace=target),
    ]
    workspaces = SimpleNamespace(
        open_project=AsyncMock(side_effect=opened),
        close=AsyncMock(return_value=None),
        retire_project_source=AsyncMock(),
    )
    monkeypatch.setattr(module, "SandboxWorkspaceService", lambda _db: workspaces)
    monkeypatch.setattr(module.project_repo, "get", AsyncMock(return_value=project))
    monkeypatch.setattr(module.job_repo, "get", AsyncMock(return_value=job))
    monkeypatch.setattr(module.job_repo, "lock_workspace_attempt", AsyncMock(return_value=job))
    monkeypatch.setattr(module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(
        module.SandboxConnectionService,
        "get",
        AsyncMock(return_value=SimpleNamespace(is_active=True, name="Cloud")),
    )
    db = MagicMock(spec=AsyncSession)
    service = ProjectWorkspaceTransferService(db)
    monkeypatch.setattr(service, "context", AsyncMock(return_value=ctx))
    monkeypatch.setattr(service, "_progress", AsyncMock())
    return SimpleNamespace(
        service=service,
        db=db,
        ctx=ctx,
        project=project,
        payload=payload,
        job=job,
        source=source,
        target=target,
        workspaces=workspaces,
    )


async def test_binary_text_empty_directories_and_private_paths(transfer):
    result = await transfer.service.run(transfer.payload, attempt=1)
    assert result.copied_files == result.total_files == 2
    assert await transfer.target.read_bytes("notes/data.bin") == b"\x00\xffbinary"
    assert await transfer.target.read_text("notes/a.md") == "  # Wiki\n"
    assert await transfer.target.exists("notes/empty")
    assert not await transfer.target.exists(".agenticos/private")
    assert not await transfer.target.exists("node_modules/installed-package.js")
    assert transfer.project.workspace_generation == project_move_generation(
        transfer.payload.transfer_id, 1
    )
    assert transfer.project.sandbox_connection_id == transfer.payload.target_connection_id
    transfer.workspaces.retire_project_source.assert_awaited_once()
    assert transfer.workspaces.close.await_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        "write",
        "verify",
        "lease",
        "flush",
        "occupied",
        "authority",
        "replaced",
        "generation",
        "inactive",
        "missing",
    ],
)
async def test_failures_never_activate_or_retire_the_source(transfer, monkeypatch, failure):
    if failure == "write":
        monkeypatch.setattr(
            transfer.target, "write_bytes", AsyncMock(side_effect=OSError("disk full"))
        )
    elif failure == "verify":
        monkeypatch.setattr(transfer.target, "read_bytes", AsyncMock(return_value=b"corrupt"))
    elif failure == "lease":
        module.job_repo.lock_workspace_attempt.return_value = None
    elif failure == "flush":
        transfer.workspaces.close.side_effect = [
            SimpleNamespace(error=OSError("flush failed")),
            None,
        ]
    elif failure == "occupied":
        await transfer.target.write_text("existing", "do not overwrite")
    elif failure == "authority":
        module.resolve_access.return_value = False
    elif failure == "replaced":
        transfer.job.payload = MOVE_PROJECT_WORKSPACE.dump(
            transfer.payload.model_copy(update={"transfer_id": uuid4()})
        )
    elif failure == "generation":
        transfer.project.workspace_generation = uuid4()
    elif failure == "inactive":
        module.SandboxConnectionService.get.return_value.is_active = False
    elif failure == "missing":
        module.project_repo.get.return_value = None
    original = transfer.project.workspace_generation
    with pytest.raises((OSError, AlreadyExistsError, BadRequestError, AuthorizationError)):
        await transfer.service.run(transfer.payload, attempt=1)
    assert transfer.project.workspace_generation == original
    assert transfer.project.backend == "state"
    assert await transfer.source.read_text("notes/a.md") == "  # Wiki\n"
    transfer.workspaces.retire_project_source.assert_not_awaited()


async def test_retry_after_activation_does_not_copy_again(transfer):
    transfer.project.workspace_generation = project_move_generation(transfer.payload.transfer_id, 1)
    transfer.job.result = {"copied_files": 2, "total_files": 2, "copied_bytes": 20}
    result = await transfer.service.run(transfer.payload, attempt=2)
    assert result.copied_files == 2
    transfer.workspaces.open_project.assert_not_awaited()


@pytest.mark.parametrize("limit", ["MAX_ENTRIES", "MAX_FILE_BYTES", "MAX_TOTAL_BYTES"])
async def test_manifest_limits_are_checked_before_copy(transfer, monkeypatch, limit):
    monkeypatch.setattr(module, limit, 1)
    with pytest.raises(BadRequestError, match="supports"):
        await manifest(transfer.source)


async def test_manifest_refuses_links_and_unknown_file_sizes(monkeypatch):
    remote = SimpleNamespace(
        working_dir=AsyncMock(return_value="/work"),
        list_dir=AsyncMock(
            return_value=[FileEntry(name="link", path="/work/link", is_dir=False, size=1)]
        ),
        realpath=AsyncMock(return_value="/elsewhere"),
        stat=AsyncMock(),
    )
    with pytest.raises(BadRequestError, match="symbolic"):
        await manifest(remote)
    remote.realpath.return_value = "/work/link"
    remote.stat.return_value = FileEntry(name="link", path="/work/link", is_dir=False, size=None)
    with pytest.raises(BadRequestError, match="measure"):
        await manifest(remote)


@pytest.mark.parametrize("path", ["/work/../escape", "/work"])
async def test_manifest_refuses_escaping_or_repeated_entries(path):
    remote = SimpleNamespace(
        working_dir=AsyncMock(return_value="/work"),
        list_dir=AsyncMock(return_value=[FileEntry(name="bad", path=path, is_dir=True, size=None)]),
    )
    with pytest.raises(BadRequestError, match="invalid"):
        await manifest(remote)


async def test_queue_is_in_the_request_transaction(transfer, monkeypatch):
    monkeypatch.setattr(module.ProjectService, "get", AsyncMock(return_value=transfer.project))
    monkeypatch.setattr(module.project_repo, "has_active_runs", AsyncMock(return_value=False))
    monkeypatch.setattr(
        module.agent_workspace_repo, "get_for_project", AsyncMock(return_value=None)
    )
    queued = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(module, "enqueue", queued)
    result = await transfer.service.queue(
        transfer.ctx,
        transfer.project.id,
        ProjectWorkspaceMoveRequest(
            backend="service", sandbox_connection_id=transfer.payload.target_connection_id
        ),
    )
    assert result.status == "queued"
    assert transfer.project.workspace_move_job_id == result.job_id
    transfer.db.commit.assert_not_called()
    payload = queued.call_args.args[2]
    assert payload.organization_id == transfer.ctx.organization_id
    assert payload.source_generation is None


@pytest.mark.parametrize(
    "reason",
    [
        "active_run",
        "same",
        "inactive",
        "no_connection",
        "state_connection",
        "deduped",
        "permission",
    ],
)
async def test_queue_refusals(transfer, monkeypatch, reason):
    monkeypatch.setattr(module.ProjectService, "get", AsyncMock(return_value=transfer.project))
    monkeypatch.setattr(
        module.project_repo, "has_active_runs", AsyncMock(return_value=reason == "active_run")
    )
    monkeypatch.setattr(
        module.agent_workspace_repo, "get_for_project", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(module, "enqueue", AsyncMock(return_value=None))
    data = ProjectWorkspaceMoveRequest(
        backend="service", sandbox_connection_id=transfer.payload.target_connection_id
    )
    ctx = transfer.ctx
    if reason == "same":
        data = ProjectWorkspaceMoveRequest(backend="state")
    if reason == "state_connection":
        data = ProjectWorkspaceMoveRequest(backend="state", sandbox_connection_id=uuid4())
    if reason == "no_connection":
        data = ProjectWorkspaceMoveRequest(backend="service")
    if reason == "inactive":
        module.SandboxConnectionService.get.return_value.is_active = False
    if reason == "permission":
        ctx = AuthContext(user_id=uuid4(), organization_id=ctx.organization_id, role="member")
    with pytest.raises((BadRequestError, AlreadyExistsError, AuthorizationError)):
        await transfer.service.queue(ctx, transfer.project.id, data)


@pytest.mark.parametrize("status", ["queued", "running", "dead", "succeeded", "cancelled"])
async def test_write_barrier_uses_current_job_state(transfer, status):
    transfer.job.status = status
    if status in ("queued", "running"):
        with pytest.raises(AlreadyExistsError):
            await guard.require_available(transfer.db, transfer.project)
    else:
        await guard.require_available(transfer.db, transfer.project)


def test_attempt_is_required_and_generations_are_isolated():
    with pytest.raises(RuntimeError):
        current_attempt_number()
    with running(Attempt(2, 3)):
        assert current_attempt_number() == 2
    transfer_id = uuid4()
    assert project_move_generation(transfer_id, 1) != project_move_generation(transfer_id, 2)


@pytest.mark.parametrize("missing", ["member", "user", "inactive", "none"])
async def test_worker_reestablishes_person_authority(transfer, monkeypatch, missing):
    monkeypatch.setattr(
        module.member_repo,
        "get_active",
        AsyncMock(return_value=None if missing == "member" else SimpleNamespace(role="owner")),
    )
    monkeypatch.setattr(
        module.user_repo,
        "get_by_id",
        AsyncMock(
            return_value=None
            if missing == "user"
            else SimpleNamespace(is_active=missing != "inactive", is_app_admin=False)
        ),
    )
    service = ProjectWorkspaceTransferService(transfer.db)
    if missing == "none":
        ctx = await service.context(transfer.payload)
        assert ctx.subject_id == transfer.payload.user_id
    else:
        with pytest.raises(AuthenticationError):
            await service.context(transfer.payload)


async def test_worker_reestablishes_api_key_authority(transfer, monkeypatch):
    lookup = AsyncMock(return_value=transfer.ctx)
    monkeypatch.setattr(module.ApiKeyService, "context_for_key", lookup)
    payload = transfer.payload.model_copy(update={"api_key_id": uuid4()})
    assert await ProjectWorkspaceTransferService(transfer.db).context(payload) == transfer.ctx
    lookup.assert_awaited_once_with(payload.api_key_id, organization_id=payload.organization_id)


@pytest.mark.parametrize(
    "case",
    [
        "changed_size",
        "changed_tree",
        "source_flush",
        "empty_source",
        "stored_target",
        "lease_during_copy",
    ],
)
async def test_copy_additional_boundaries(transfer, monkeypatch, case):
    if case == "changed_size":
        monkeypatch.setattr(transfer.source, "read_bytes", AsyncMock(return_value=b"changed-size"))
    elif case == "changed_tree":
        original = module.manifest
        calls = 0

        async def changing(workspace):
            nonlocal calls
            calls += 1
            entries = await original(workspace)
            return entries[:-1] if calls == 3 else entries

        monkeypatch.setattr(module, "manifest", changing)
    elif case == "source_flush":
        transfer.workspaces.close.side_effect = [
            None,
            SimpleNamespace(error=OSError("source flush")),
        ]
    elif case == "empty_source":
        transfer.workspaces.open_project.side_effect = [
            SimpleNamespace(workspace=workspace(), row_id=None),
            SimpleNamespace(workspace=transfer.target),
        ]
        transfer.payload = transfer.payload.model_copy(update={"source_workspace_id": None})
        transfer.job.payload = MOVE_PROJECT_WORKSPACE.dump(transfer.payload)
    elif case == "stored_target":
        transfer.payload = transfer.payload.model_copy(
            update={"target_backend": "state", "target_connection_id": None}
        )
        transfer.job.payload = MOVE_PROJECT_WORKSPACE.dump(transfer.payload)
    elif case == "lease_during_copy":
        transfer.service._progress.side_effect = AlreadyExistsError(message="lease expired")
    if case in ("empty_source", "stored_target"):
        await transfer.service.run(transfer.payload, attempt=1)
        assert transfer.project.workspace_generation is not None
    else:
        with pytest.raises((BadRequestError, OSError, AlreadyExistsError)):
            await transfer.service.run(transfer.payload, attempt=1)
        assert transfer.project.workspace_generation is None


@pytest.mark.parametrize("case", ["none_id", "missing", "denied", "available"])
async def test_workspace_guard_locks_and_checks_project(transfer, monkeypatch, case):
    monkeypatch.setattr(guard, "resolve_access", AsyncMock(return_value=case != "denied"))
    transfer.project.workspace_move_job_id = None
    if case == "missing":
        module.project_repo.get.return_value = None
    if case == "available":
        assert (
            await guard.project_for_workspace(transfer.db, transfer.ctx, transfer.project.id)
            == transfer.project
        )
        assert module.project_repo.get.call_args.kwargs["for_update"]
    else:
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await guard.project_for_workspace(
                transfer.db, transfer.ctx, None if case == "none_id" else transfer.project.id
            )


@pytest.mark.parametrize("valid", [True, False])
async def test_progress_uses_the_same_lease_fence(transfer, monkeypatch, valid):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session():
        yield transfer.db

    monkeypatch.setattr(module, "get_worker_db_context", session)
    progress = AsyncMock(return_value=valid)
    monkeypatch.setattr(module.job_repo, "workspace_move_progress", progress)
    from app.schemas.project import ProjectWorkspaceProgress

    if valid:
        await ProjectWorkspaceTransferService._progress(
            transfer.job.id, 2, ProjectWorkspaceProgress()
        )
    else:
        with pytest.raises(AlreadyExistsError):
            await ProjectWorkspaceTransferService._progress(
                transfer.job.id, 2, ProjectWorkspaceProgress()
            )
    assert progress.call_args.kwargs["attempt"] == 2


@pytest.mark.parametrize("active", [True, False])
async def test_cleanup_never_removes_an_active_generation(transfer, monkeypatch, active):
    from contextlib import asynccontextmanager

    from app.worker.tasks import project_tasks

    @asynccontextmanager
    async def session():
        yield transfer.db

    monkeypatch.setattr(project_tasks, "get_worker_db_context", session)
    transfer.project.workspace_generation = (
        project_move_generation(transfer.payload.transfer_id, 2) if active else None
    )
    cleanup = AsyncMock()
    monkeypatch.setattr(
        project_tasks,
        "SandboxWorkspaceService",
        lambda _db: SimpleNamespace(cleanup_project_copy=cleanup),
    )
    await project_tasks.settle_project_copies(transfer.payload, "dead")
    assert cleanup.await_count == (2 if active else 3)
    keys = [call.kwargs["key"] for call in cleanup.call_args_list]
    assert (
        not any(
            key.endswith(project_move_generation(transfer.payload.transfer_id, 2).hex)
            for key in keys
        )
        if active
        else len(keys) == 3
    )
    await project_tasks.settle_project_copies(
        transfer.payload.model_copy(update={"target_connection_id": None}), "dead"
    )
    assert cleanup.await_count == len(keys)


async def test_handler_runs_with_worker_attempt_and_commits_before_cleanup(transfer, monkeypatch):
    from contextlib import asynccontextmanager

    from app.worker.tasks import project_tasks

    order = []

    @asynccontextmanager
    async def session():
        yield transfer.db
        order.append("commit")

    runner = AsyncMock(return_value=module.ProjectWorkspaceProgress(copied_files=2))

    async def clean(_payload, _why):
        order.append("cleanup")

    monkeypatch.setattr(project_tasks, "get_worker_db_context", session)
    monkeypatch.setattr(
        project_tasks, "ProjectWorkspaceTransferService", lambda _db: SimpleNamespace(run=runner)
    )
    monkeypatch.setattr(project_tasks, "settle_project_copies", clean)
    with running(Attempt(2, 3)):
        result = await project_tasks.move_project_workspace(transfer.payload)
    assert result.copied_files == 2
    assert order == ["commit", "cleanup"]
    assert runner.call_args.kwargs["attempt"] == 2


def test_stored_listing_preserves_empty_folders():
    from app.services.sandbox_workspace import stored_entries

    entries = stored_entries({}, ["/", "/notes", "/notes/empty", "/.agenticos"])
    assert [entry["path"] for entry in entries] == ["/notes", "/notes/empty"]


async def test_retired_transfer_jobs_cannot_reuse_attempt_generations(transfer):
    from app.services.background_jobs import BackgroundJobService

    transfer.job.kind = MOVE_PROJECT_WORKSPACE.kind
    with pytest.raises(BadRequestError, match="new transfer"):
        await BackgroundJobService(transfer.db).retry(
            transfer.job.id, actor_user_id=transfer.ctx.subject_id
        )


@pytest.mark.parametrize("kind", ["state", "service", "missing", "wrong_project"])
async def test_verified_source_retirement_is_scoped_and_defers_remote_cleanup(
    transfer, monkeypatch, kind
):
    from app.repositories import agent_workspace as repository
    from app.services.sandbox_workspace import SandboxWorkspaceService

    service = SandboxWorkspaceService(transfer.db)
    source = SimpleNamespace(
        id=uuid4(),
        project_id=uuid4() if kind == "wrong_project" else transfer.project.id,
        backend=kind,
    )
    monkeypatch.setattr(
        repository, "get", AsyncMock(return_value=None if kind == "missing" else source)
    )
    deleted = AsyncMock()
    monkeypatch.setattr(repository, "delete", deleted)
    purge = AsyncMock()
    monkeypatch.setattr(service, "_purge_remote", purge)
    if kind == "wrong_project":
        with pytest.raises(BadRequestError):
            await service.retire_project_source(
                transfer.ctx, source_id=source.id, project_id=transfer.project.id
            )
        deleted.assert_not_awaited()
    else:
        await service.retire_project_source(
            transfer.ctx, source_id=source.id, project_id=transfer.project.id
        )
        assert deleted.await_count == (0 if kind == "missing" else 1)
        assert purge.await_count == (1 if kind == "service" else 0)
    key = "private-copy"
    await service.cleanup_project_copy(
        transfer.ctx, connection_id=transfer.payload.target_connection_id, key=key
    )
    row = purge.call_args.args[1]
    assert row.organization_id == transfer.ctx.organization_id and row.scope_key == key


@pytest.mark.parametrize("action", ["update", "delete"])
async def test_sandbox_connection_changes_wait_for_active_project_transfers(
    transfer, monkeypatch, action
):
    from app.schemas.sandbox_connection import SandboxConnectionUpdate
    from app.services.sandbox_connection import SandboxConnectionService

    monkeypatch.setattr(
        module.project_repo, "active_moves_for_connection", AsyncMock(return_value=True)
    )
    service = SandboxConnectionService(transfer.db)
    with pytest.raises(BadRequestError, match="transfer"):
        if action == "update":
            await service.update(
                transfer.ctx,
                transfer.payload.target_connection_id,
                SandboxConnectionUpdate(name="Changed"),
            )
        else:
            await service.delete(transfer.ctx, transfer.payload.target_connection_id)
