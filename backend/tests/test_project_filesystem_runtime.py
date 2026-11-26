"""A live mount is exposed only after admission commits and stays run-owned."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.audience import RunAudience
from app.core.exceptions import AuthorizationError, ConcurrentChangeError, ExternalServiceError
from app.core.permissions import AuthContext
from app.schemas.project_filesystem import FsFailure, FsSuccess
from app.schemas.project_filesystem_authority import (
    ProjectFilesystemAuthority,
    ProjectFilesystemLeaseRead,
)
from app.services import project_filesystem_runtime as module
from app.services import run_project_workspace

pytestmark = pytest.mark.anyio


@pytest.fixture
def runtime(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    authority = ProjectFilesystemAuthority(
        actor=ctx,
        audience=RunAudience(user_id=ctx.user_id),
        granted_scopes=frozenset({"projects:read", "projects:write"}),
        conversation_project_id=None,
        conversation_id=uuid4(),
    )
    project_id, generation, binding_id = uuid4(), uuid4(), uuid4()
    project = SimpleNamespace(workspace_generation=generation)
    project_lookup = AsyncMock(return_value=(ctx, project))
    monkeypatch.setattr(run_project_workspace.ProjectRunAuthority, "project", project_lookup)
    events = []
    commit_failure = []

    @asynccontextmanager
    async def transaction():
        events.append("begin")
        yield AsyncMock()
        if commit_failure:
            raise commit_failure.pop()
        events.append("commit")

    monkeypatch.setattr(module, "get_db_context", transaction)
    support = AsyncMock(return_value=FsSuccess())
    monkeypatch.setattr(module.ProjectFilesystemService, "exclusive_create_support", support)
    leases = {}

    async def issue(**kwargs):
        key = kwargs["project_id"], kwargs["generation"]
        if key not in leases:
            lease_id = uuid4()
            leases[key] = ProjectFilesystemLeaseRead(
                id=lease_id,
                project_id=key[0],
                workspace_generation=key[1],
                path=f"/project/{lease_id}",
                expires_at=datetime.now(UTC) + timedelta(seconds=90),
            )
        events.append("issue")
        return leases[key]

    issue_mock = AsyncMock(side_effect=issue)
    renew, revoke = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module.ProjectFilesystemBindingService, "issue_lease", issue_mock)
    monkeypatch.setattr(module.ProjectFilesystemBindingService, "renew", renew)
    monkeypatch.setattr(module.ProjectFilesystemBindingService, "revoke", revoke)
    return SimpleNamespace(
        runtime=module.ProjectFilesystemRuntime(uuid4(), authority),
        binding=binding_id,
        project_id=project_id,
        generation=generation,
        project=project,
        lookup=project_lookup,
        support=support,
        issue=issue_mock,
        renew=renew,
        revoke=revoke,
        events=events,
        commit_failure=commit_failure,
    )


async def test_committed_reuse_switch_release_and_select_again(runtime):
    r = runtime
    path = await r.runtime.directory(r.binding, r.project_id, r.generation)
    assert r.events[-1] == "commit"
    assert await r.runtime.directory(r.binding, r.project_id, r.generation) == path
    assert r.lookup.await_count == 2
    assert r.revoke.await_count == 0
    other = uuid4()
    assert await r.runtime.directory(r.binding, other, r.generation) != path
    assert r.revoke.await_count == 1
    await r.runtime.close()
    await r.runtime.close()
    assert r.revoke.await_count == 2
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    await r.runtime.close()
    assert r.revoke.await_count == 3


@pytest.mark.parametrize("refusal", ["auth", "generation", "native", "commit"])
async def test_refusal_never_exposes_a_directory_and_fences(runtime, refusal):
    r = runtime
    expected = AuthorizationError
    if refusal == "auth":
        r.lookup.side_effect = AuthorizationError(message="revoked")
    elif refusal == "generation":
        r.project.workspace_generation = uuid4()
        expected = ConcurrentChangeError
    elif refusal == "native":
        r.support.return_value = FsFailure(errno=95, message="unsupported")
        expected = ExternalServiceError
    else:
        r.commit_failure.append(ValueError("commit failed"))
        expected = ValueError
    with pytest.raises(expected):
        await r.runtime.directory(r.binding, r.project_id, r.generation)
    with pytest.raises(RuntimeError, match="unavailable"):
        r.runtime.check_health()
    assert r.runtime._task is None
    await r.runtime.close()
    assert r.revoke.await_count == (1 if refusal == "commit" else 0)


async def test_renewal_failure_is_observed_fences_and_revokes(runtime, monkeypatch):
    r = runtime
    monkeypatch.setattr(module, "RENEW_SECONDS", 0)
    r.renew.side_effect = ValueError("database unavailable")
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    task = r.runtime._task
    assert task is not None
    with pytest.raises(ValueError, match="database unavailable"):
        await task
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError, match="unavailable"):
        await r.runtime.directory(r.binding, r.project_id, r.generation)
    await r.runtime.close()
    r.revoke.assert_awaited_once()


async def test_renewal_reauthorizes_generation(runtime, monkeypatch):
    r = runtime
    monkeypatch.setattr(module, "RENEW_SECONDS", 0)
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    r.project.workspace_generation = uuid4()
    task = r.runtime._task
    assert task is not None
    with pytest.raises(ConcurrentChangeError):
        await task
    await asyncio.sleep(0)
    r.renew.assert_not_awaited()
    await r.runtime.close()


async def test_concurrent_selection_serialized_and_renewal_commits(runtime, monkeypatch):
    r = runtime
    monkeypatch.setattr(module, "RENEW_SECONDS", 0)
    first, second = await asyncio.gather(
        r.runtime.directory(r.binding, r.project_id, r.generation),
        r.runtime.directory(r.binding, r.project_id, r.generation),
    )
    assert first == second
    for _ in range(20):
        if r.renew.await_count:
            break
        await asyncio.sleep(0)
    assert r.renew.await_count
    await r.runtime.close()
    assert r.events[-1] == "commit"


async def test_revoke_failure_remains_retryable(runtime):
    r = runtime
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    r.revoke.side_effect = ValueError("revoke failed")
    with pytest.raises(ValueError, match="revoke failed"):
        await r.runtime.close()
    r.revoke.side_effect = None
    await r.runtime.close()
    assert r.revoke.await_count == 2


async def test_cancelled_admission_keeps_ambiguous_lease_for_cleanup(runtime, monkeypatch):
    r = runtime
    entered = asyncio.Event()

    @asynccontextmanager
    async def interrupted_commit():
        yield AsyncMock()
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module, "get_db_context", interrupted_commit)
    admission = asyncio.create_task(r.runtime.directory(r.binding, r.project_id, r.generation))
    await entered.wait()
    admission.cancel()
    with pytest.raises(asyncio.CancelledError):
        await admission

    @asynccontextmanager
    async def transaction():
        yield AsyncMock()

    monkeypatch.setattr(module, "get_db_context", transaction)
    await r.runtime.close()
    r.revoke.assert_awaited_once()


async def test_cancelled_cleanup_finishes_revoke_and_preserves_cancellation(runtime):
    r = runtime
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def revoke(**kwargs):
        entered.set()
        await finish.wait()

    r.revoke.side_effect = revoke
    closing = asyncio.create_task(r.runtime.close())
    await entered.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert r.runtime._lease is None
    await r.runtime.close()


async def test_cancelled_cleanup_reports_revoke_failure_as_cause(runtime):
    r = runtime
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def revoke(**kwargs):
        entered.set()
        await finish.wait()
        raise ValueError("cleanup failed")

    r.revoke.side_effect = revoke
    closing = asyncio.create_task(r.runtime.close())
    await entered.wait()
    closing.cancel()
    await asyncio.sleep(0)
    finish.set()
    with pytest.raises(BaseExceptionGroup) as result:
        await closing
    assert isinstance(result.value.exceptions[0], asyncio.CancelledError)
    assert isinstance(result.value.exceptions[1], ValueError)
    r.revoke.side_effect = None
    await r.runtime.close()


async def test_switch_admission_failure_stops_empty_supervisor(runtime, monkeypatch):
    r = runtime
    monkeypatch.setattr(module, "RENEW_SECONDS", 0)
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    r.issue.side_effect = ValueError("new lease refused")
    task = r.runtime._task
    assert task is not None
    with pytest.raises(ValueError, match="new lease refused"):
        await r.runtime.directory(r.binding, uuid4(), r.generation)
    await task
    await asyncio.sleep(0)
    await r.runtime.close()


async def test_close_cancels_renewal_while_database_owns_lock(runtime, monkeypatch):
    r = runtime
    monkeypatch.setattr(module, "RENEW_SECONDS", 0)
    entered = asyncio.Event()

    async def blocked_renew(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    r.renew.side_effect = blocked_renew
    await r.runtime.directory(r.binding, r.project_id, r.generation)
    await entered.wait()
    async with asyncio.timeout(1):
        await r.runtime.close()
    r.revoke.assert_awaited_once()


async def test_close_settles_admission_already_inside_transaction(runtime):
    r = runtime
    original = r.issue.side_effect
    entered, finish = asyncio.Event(), asyncio.Event()

    async def issue(**kwargs):
        entered.set()
        await finish.wait()
        return await original(**kwargs)

    r.issue.side_effect = issue
    admission = asyncio.create_task(r.runtime.directory(r.binding, r.project_id, r.generation))
    await entered.wait()
    closing = asyncio.create_task(r.runtime.close())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    finish.set()
    await admission
    await closing
    assert r.runtime._task is None
    r.revoke.assert_awaited_once()


async def test_concurrent_close_shares_cleanup_and_refuses_new_admission(runtime, monkeypatch):
    r = runtime
    entered, finish = asyncio.Event(), asyncio.Event()
    original = r.runtime._close

    async def delayed_close():
        entered.set()
        await finish.wait()
        return await original()

    monkeypatch.setattr(r.runtime, "_close", delayed_close)
    first = asyncio.create_task(r.runtime.close())
    await entered.wait()
    second = asyncio.create_task(r.runtime.close())
    with pytest.raises(RuntimeError, match="closing"):
        await r.runtime.directory(r.binding, r.project_id, r.generation)
    finish.set()
    await asyncio.gather(first, second)


async def test_health_reads_finished_task_before_callback(runtime):
    r = runtime

    async def finished():
        return None

    task = asyncio.create_task(finished())
    await task
    r.runtime._task = task
    with pytest.raises(RuntimeError, match="unavailable"):
        r.runtime.check_health()
    await r.runtime.close()


async def test_readonly_mount_authorizes_and_commits_without_write_probe(runtime):
    r = runtime
    r.runtime.authority = r.runtime.authority.model_copy(
        update={"granted_scopes": frozenset({"projects:read"})}
    )
    path = await r.runtime.directory(r.binding, r.project_id, r.generation)
    assert path.startswith("/project/")
    r.lookup.assert_awaited_once()
    r.support.assert_not_awaited()
    assert r.events[-1] == "commit"
    issued = r.issue.await_args.kwargs["authority"]
    assert issued.granted_scopes == frozenset({"projects:read"})
    await r.runtime.close()
