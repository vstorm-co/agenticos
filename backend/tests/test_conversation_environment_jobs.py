"""Jobs retain cleanup obligations and never replay interrupted provider creation."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthorizationError
from app.db.models.conversation_environment import ConversationEnvironment
from app.services.conversation_environment_policy import EnvironmentNotReady
from app.services.conversation_environment_resources import DesktopEnvironmentResource
from app.worker.attempt import Attempt, running
from app.worker.jobs import ConversationEnvironmentPayload
from app.worker.tasks import conversation_environment_tasks as jobs

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.fixture
def case(monkeypatch):
    org, identity, owner, conversation = (uuid4() for _ in range(4))
    payload = ConversationEnvironmentPayload(
        environment_id=identity, organization_id=org, revision=1
    )
    row = ConversationEnvironment(
        id=identity,
        organization_id=org,
        user_id=owner,
        conversation_id=conversation,
        revision=1,
        state="ready",
        execution_target="agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )
    resource = DesktopEnvironmentResource(
        environment_id=identity,
        organization_id=org,
        backend="daemon",
        credential="private-token",
        daemon_url="http://provider:8765",
        width=1280,
        height=800,
    )
    db = AsyncMock()

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(jobs, "get_worker_db_context", session)
    monkeypatch.setattr(jobs.environments, "for_worker", AsyncMock(return_value=row))
    monkeypatch.setattr(
        jobs.ConversationEnvironmentService, "cleanup_resource", AsyncMock(return_value=resource)
    )
    monkeypatch.setattr(jobs.ConversationEnvironmentService, "cleaned", AsyncMock())
    monkeypatch.setattr(jobs.ConversationEnvironmentService, "failed", AsyncMock())
    monkeypatch.setattr(jobs.ConversationEnvironmentService, "expire", AsyncMock())
    monkeypatch.setattr(jobs.ConversationEnvironmentService, "sweep", AsyncMock())
    monkeypatch.setattr(
        jobs.ConversationEnvironmentService,
        "live",
        AsyncMock(return_value=(row, SimpleNamespace(), resource)),
    )
    monkeypatch.setattr(jobs, "current_actor", AsyncMock())
    monkeypatch.setattr(jobs.runtime, "start_environment", AsyncMock())
    monkeypatch.setattr(jobs.runtime, "dispose", AsyncMock())
    monkeypatch.setattr(jobs.runtime, "picture", AsyncMock())
    closed = []

    @asynccontextmanager
    async def view(_resource, _resolved):
        try:
            yield SimpleNamespace()
        finally:
            closed.append(True)

    monkeypatch.setattr(jobs.runtime, "open_view", view)
    return SimpleNamespace(db=db, row=row, resource=resource, payload=payload, closed=closed)


async def test_provision_requires_the_claimed_job_attempt_and_never_invents_one(case):
    with pytest.raises(RuntimeError, match="claimed job"):
        await jobs.provision_environment(case.payload)
    jobs.runtime.start_environment.assert_not_awaited()
    with running(Attempt(2, 2)):
        await jobs.provision_environment(case.payload)
    jobs.runtime.start_environment.assert_awaited_once_with(case.payload, attempt=2)


async def test_cleanup_keeps_the_journal_until_remote_disposal_succeeds(case):
    jobs.runtime.dispose.side_effect = OSError("Provider unavailable")
    with pytest.raises(OSError):
        await jobs.cleanup_environment(case.payload)
    jobs.ConversationEnvironmentService.cleaned.assert_not_awaited()
    jobs.runtime.dispose.side_effect = None
    await jobs.cleanup_environment(case.payload)
    jobs.ConversationEnvironmentService.cleaned.assert_awaited_once_with(case.payload)


async def test_stale_cleanup_job_performs_no_remote_effect(case):
    jobs.ConversationEnvironmentService.cleanup_resource.return_value = None
    await jobs.cleanup_environment(case.payload)
    jobs.runtime.dispose.assert_not_awaited()


@pytest.mark.parametrize("changed", ["missing", "tenant", "revision", "state", "expiry"])
async def test_stale_maintenance_job_cannot_open_any_provider(case, changed):
    if changed == "missing":
        jobs.environments.for_worker.return_value = None
    elif changed == "tenant":
        case.row.organization_id = uuid4()
    elif changed == "revision":
        case.row.revision += 1
    elif changed == "state":
        case.row.state = "expired"
    else:
        case.row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await jobs.maintain_environment(case.payload)
    jobs.runtime.picture.assert_not_awaited()
    assert case.closed == []


@pytest.mark.parametrize("missing", ["user_id", "conversation_id"])
async def test_orphan_maintenance_expires_without_contacting_the_provider(case, missing):
    setattr(case.row, missing, None)
    await jobs.maintain_environment(case.payload)
    jobs.ConversationEnvironmentService.expire.assert_awaited_once_with(case.row)
    jobs.runtime.picture.assert_not_awaited()


async def test_maintenance_attaches_exact_resource_then_only_detaches(case):
    await jobs.maintain_environment(case.payload)
    jobs.runtime.picture.assert_awaited_once()
    assert case.closed == [True]
    jobs.runtime.dispose.assert_not_awaited()


@pytest.mark.parametrize(
    "failure",
    [
        AuthorizationError(message="Owner revoked"),
        EnvironmentNotReady("environment_expired", "Provider reference lost"),
        OSError("Provider disconnected"),
    ],
)
async def test_expected_maintenance_refusal_expires_the_same_revision(case, failure):
    jobs.runtime.picture.side_effect = failure
    await jobs.maintain_environment(case.payload)
    assert case.closed == [True]
    jobs.ConversationEnvironmentService.expire.assert_awaited_once_with(case.row)


async def test_a_maintenance_bug_is_observable_and_not_disguised_as_expiry(case):
    jobs.runtime.picture.side_effect = RuntimeError("Unexpected adapter defect")
    with pytest.raises(RuntimeError, match="Unexpected adapter defect"):
        await jobs.maintain_environment(case.payload)
    jobs.ConversationEnvironmentService.expire.assert_not_awaited()


async def test_sweep_and_interrupted_provision_settlement_reuse_durable_service_contract(case):
    await jobs.sweep_environments()
    jobs.ConversationEnvironmentService.sweep.assert_awaited_once()
    await jobs.settle_environment(case.payload, "Worker stopped")
    jobs.ConversationEnvironmentService.failed.assert_awaited_once_with(case.payload)


@pytest.mark.parametrize("missing", [False, True])
async def test_failed_maintenance_does_not_expire_newer_or_removed_admission(case, missing):
    jobs.runtime.picture.side_effect = OSError("Disconnected")
    current = None if missing else case.row
    jobs.environments.for_worker.side_effect = [case.row, current]
    if not missing:

        async def fail(_view):
            case.row.revision += 1
            raise OSError("Disconnected")

        jobs.runtime.picture.side_effect = fail
    await jobs.maintain_environment(case.payload)
    jobs.ConversationEnvironmentService.expire.assert_not_awaited()
