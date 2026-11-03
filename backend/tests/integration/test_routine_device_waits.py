"""Postgres owns device waits and their admission, deduplication and redaction."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.organization import Organization
from app.db.models.routine_device_wait import RoutineDeviceWait
from app.db.models.session import Session
from app.db.models.user import User
from app.repositories import agent_trigger_repo, personal_data_repo, retention_repo
from app.repositories import routine_device_wait as repo
from app.schemas.local_target import LocalTarget
from app.services.routine_actions import activation_intent
from app.services.routine_devices import (
    RoutineActivationObsolete,
    RoutineLocalConsentRequired,
    admit_activation,
)

pytestmark = pytest.mark.anyio


@dataclass
class World:
    trigger: AgentTrigger
    user: User
    device: Session
    ctx: AuthContext


async def world(db: AsyncSession, *, event: bool = False) -> World:
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id, name="Monitor", slug=f"monitor-{uuid4()}", owner_user_id=user.id
    )
    device = Session(
        user_id=user.id,
        refresh_token_hash=str(uuid4()),
        app_platform="macos",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add_all([agent, device])
    await db.flush()
    local = LocalTarget(
        folder="/work",
        mode="read_only",
        device_id=device.id,
        routine_grant=uuid4(),
        operations={"read": True, "write": False, "execute": False},
    )
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Read report",
        trigger_type="event" if event else "schedule",
        event_source="webhook" if event else None,
        event_secret_encrypted="sealed" if event else None,
        secret_key_version=1 if event else None,
        interval_seconds=None if event else 300,
        next_fire_at=None if event else datetime.now(UTC),
        runs_as_creator=True,
        local_target=local.model_dump(mode="json"),
    )
    db.add(trigger)
    await db.flush()
    ctx = AuthContext(
        user_id=user.id,
        organization_id=org.id,
        role=OrgRoleName.OWNER,
        routine_id=trigger.id,
        fired_as_creator="event" if event else "schedule",
    )
    return World(trigger, user, device, ctx)


async def park(
    db: AsyncSession, w: World, *, context: str | None = None, activation: UUID | None = None
) -> UUID:
    activation = activation or uuid4()
    assert await repo.park(
        db,
        activation_id=activation,
        trigger=w.trigger,
        user_id=w.user.id,
        device_id=w.device.id,
        intent_hash=activation_intent(w.trigger),
        event_context=context,
    )
    return activation


async def test_scheduled_waits_coalesce_without_overwriting_the_original_activation(
    db: AsyncSession,
) -> None:
    w = await world(db)
    activation = await park(db, w)
    assert not await repo.park(
        db,
        activation_id=uuid4(),
        trigger=w.trigger,
        user_id=w.user.id,
        device_id=w.device.id,
        intent_hash="different",
        event_context=None,
    )
    trigger = await agent_trigger_repo.get_by_id(db, w.trigger.id, fresh=True)
    assert trigger.waiting_device_count == 1
    assert trigger.waiting_device_since is not None
    assert (await repo.get(db, activation)).intent_hash == activation_intent(w.trigger)


async def test_each_distinct_event_retains_its_own_context_but_retry_never_rewrites_it(
    db: AsyncSession,
) -> None:
    w = await world(db, event=True)
    first = await park(db, w, context="first private event")
    second = await park(db, w, context="second event")
    assert first != second
    assert not await repo.park(
        db,
        activation_id=first,
        trigger=w.trigger,
        user_id=w.user.id,
        device_id=w.device.id,
        intent_hash=activation_intent(w.trigger),
        event_context="replacement",
    )
    assert (await repo.get(db, first)).event_context == "first private event"
    assert len(await repo.pending(db)) == 2


async def test_admission_and_rollback_leave_no_started_gap_and_second_admission_is_refused(
    db: AsyncSession,
) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="event")
    ctx = replace(w.ctx, routine_activation_id=activation)
    savepoint = await db.begin_nested()
    await admit_activation(db, ctx)
    assert (await repo.get(db, activation)).status == "started"
    assert (await repo.get(db, activation)).event_context is None
    await savepoint.rollback()
    assert (await repo.get(db, activation)).status == "waiting"
    await admit_activation(db, ctx)
    with pytest.raises(RoutineActivationObsolete):
        await admit_activation(db, ctx)


@pytest.mark.parametrize("change", ["pause", "prompt", "folder", "owner", "end", "acting"])
async def test_changed_authority_cancels_old_wait_without_retargeting_its_event(
    db: AsyncSession, change: str
) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="private event")
    if change == "pause":
        w.trigger.is_active = False
    elif change == "prompt":
        w.trigger.prompt = "different task"
    elif change == "folder":
        w.trigger.local_target = w.trigger.local_target | {"folder": "/elsewhere"}
    elif change == "owner":
        w.trigger.created_by_user_id = None
    elif change == "end":
        w.trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "acting":
        w.trigger.runs_as_creator = False
    await db.flush()
    with pytest.raises(RoutineActivationObsolete):
        await admit_activation(db, replace(w.ctx, routine_activation_id=activation))
    wait = await repo.get(db, activation)
    assert wait.status == "cancelled"
    assert wait.event_context is None


async def test_other_tenant_cannot_admit_or_consume_the_wait(db: AsyncSession) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="private event")
    with pytest.raises(AuthorizationError):
        await admit_activation(
            db, replace(w.ctx, organization_id=uuid4(), routine_activation_id=activation)
        )
    assert (await repo.get(db, activation)).status == "waiting"


async def test_revoked_device_never_uses_cached_presence_to_admit(db: AsyncSession) -> None:
    w = await world(db)
    activation = await park(db, w)
    w.device.is_active = False
    await db.flush()
    with pytest.raises(RoutineLocalConsentRequired):
        await admit_activation(db, replace(w.ctx, routine_activation_id=activation))
    assert (await repo.get(db, activation)).status == "waiting"


async def test_dispatch_failure_budget_counts_each_dead_job_once_and_keeps_evidence(
    db: AsyncSession,
) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="unconsumed event")
    wait = await repo.get(db, activation)
    for count in range(1, 4):
        await repo.record_job(db, wait=wait, job_id=uuid4())
        await repo.record_admission_failure(db, wait=wait)
        await repo.record_admission_failure(db, wait=wait)
        assert wait.admission_failures == count
    await repo.fail(db, wait=wait)
    assert await repo.pending(db) == []
    assert (await repo.get(db, activation)).event_context == "unconsumed event"
    assert not await repo.settle(db, activation_id=activation, status="started")


async def test_export_is_owner_scoped_and_includes_retained_context_in_size_bound(
    db: AsyncSession,
) -> None:
    w = await world(db, event=True)
    await park(db, w, context="private event")
    assert len(await personal_data_repo.routine_device_waits_of(db, w.user.id)) == 1
    assert await personal_data_repo.routine_device_waits_of(db, uuid4()) == []
    assert await personal_data_repo.routine_device_wait_export_size(db, w.user.id) == 1024 + len(
        "private event"
    )
    assert await personal_data_repo.routine_device_wait_export_size(db, uuid4()) == 0


async def test_pause_redacts_waits_and_deletion_cascades_their_metadata(db: AsyncSession) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="private event")
    await repo.cancel_for_trigger(db, trigger_id=w.trigger.id, reason="paused")
    assert (await repo.get(db, activation)).event_context is None
    assert await repo.pending(db) == []
    await db.delete(w.trigger)
    await db.flush()
    assert (
        await db.scalar(select(RoutineDeviceWait.id).where(RoutineDeviceWait.id == activation))
        is None
    )


async def test_run_history_retention_removes_finished_context_but_keeps_offline_work(
    db: AsyncSession,
) -> None:
    w = await world(db, event=True)
    failed = await park(db, w, context="failed private event")
    waiting = await park(db, w, context="still waiting")
    row = await repo.get(db, failed)
    await repo.fail(db, wait=row)
    row.finished_at = datetime.now(UTC) - timedelta(days=40)
    await db.flush()
    cutoff = datetime.now(UTC) - timedelta(days=30)
    assert (
        await retention_repo.delete_finished_device_waits(
            db, organization_id=uuid4(), cutoff=cutoff, limit=100
        )
        == 0
    )
    assert (
        await retention_repo.delete_finished_device_waits(
            db, organization_id=w.ctx.organization_id, cutoff=cutoff, limit=100
        )
        == 1
    )
    assert await repo.get(db, failed) is None
    assert (await repo.get(db, waiting)).event_context == "still waiting"


async def test_wait_representation_never_includes_private_event_context(db: AsyncSession) -> None:
    w = await world(db, event=True)
    activation = await park(db, w, context="private event")
    assert (
        repr(await repo.get(db, activation))
        == f"<RoutineDeviceWait(id={activation}, status=waiting)>"
    )


async def test_queue_and_minute_worker_keep_one_activation_until_device_returns(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.background_job import BackgroundJob
    from app.services import agent_trigger as trigger_module
    from app.services.agent_runner import AgentRunnerService
    from app.services.agent_trigger import AgentTriggerService
    from app.services.routine_devices import RoutineDeviceOffline

    w = await world(db, event=True)
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_creator_context", AsyncMock(return_value=w.ctx))
    monkeypatch.setattr(
        service.agents, "get", AsyncMock(return_value=await db.get(Agent, w.trigger.agent_id))
    )
    monkeypatch.setattr(
        trigger_module,
        "local_device_ready",
        AsyncMock(side_effect=RoutineDeviceOffline(message="offline")),
    )
    presence = AsyncMock(return_value=None)
    monkeypatch.setattr(trigger_module.device_hub, "wait_for", presence)
    execute = AsyncMock()
    monkeypatch.setattr(AgentRunnerService, "execute", execute)
    first_job_id = await service.queue_fire(
        w.trigger.id, organization_id=w.ctx.organization_id, event_context="original private event"
    )
    first_job = await db.get(BackgroundJob, first_job_id)
    activation = UUID(first_job.payload["activation_id"])
    assert first_job.payload["event_context"] is None
    first_job.status = "running"
    await db.flush()
    await service.fire(w.trigger.id, activation_id=activation)
    assert (await repo.get(db, activation)).status == "waiting"
    execute.assert_not_awaited()
    assert await service.resume_device_waits() == 0
    first_job.status = "succeeded"
    await db.flush()
    assert await service.resume_device_waits() == 0
    presence.return_value = object()
    assert await service.resume_device_waits() == 1
    wait = await repo.get(db, activation)
    assert wait.last_job_id != first_job_id
    assert wait.event_context == "original private event"
    next_job = await db.get(BackgroundJob, wait.last_job_id)
    assert next_job.payload["activation_id"] == str(activation)
    assert next_job.payload["event_context"] is None
    assert await service.resume_device_waits() == 0
    await admit_activation(db, replace(w.ctx, routine_activation_id=activation))
    await service.fire(w.trigger.id, activation_id=activation)
    execute.assert_not_awaited()
    assert (await repo.get(db, activation)).status == "started"


async def test_queue_coalesces_scheduled_waits_but_does_not_resurrect_a_cancelled_job(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.background_job import BackgroundJob
    from app.services.agent_trigger import AgentTriggerService

    w = await world(db)
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_creator_context", AsyncMock(return_value=w.ctx))
    monkeypatch.setattr(
        service.agents, "get", AsyncMock(return_value=await db.get(Agent, w.trigger.agent_id))
    )
    job_id = await service.queue_fire(w.trigger.id, organization_id=w.ctx.organization_id)
    assert job_id is not None
    assert await service.queue_fire(w.trigger.id, organization_id=w.ctx.organization_id) is None
    job = await db.get(BackgroundJob, job_id)
    job.status = "cancelled"
    await db.flush()
    assert await service.resume_device_waits() == 0
    wait = await repo.get(db, UUID(job.payload["activation_id"]))
    assert wait.status == "cancelled"
    assert wait.reason == "job_cancelled"


async def test_three_dead_dispatches_stop_the_routine_and_keep_only_one_incident(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.background_job import BackgroundJob
    from app.services import agent_trigger as trigger_module
    from app.services.agent_trigger import AgentTriggerService

    w = await world(db, event=True)
    service = AgentTriggerService(db)
    monkeypatch.setattr(service, "_creator_context", AsyncMock(return_value=w.ctx))
    monkeypatch.setattr(
        service.agents, "get", AsyncMock(return_value=await db.get(Agent, w.trigger.agent_id))
    )
    monkeypatch.setattr(trigger_module.device_hub, "wait_for", AsyncMock(return_value=object()))
    incident = AsyncMock()
    monkeypatch.setattr(trigger_module.NotificationService, "routine_blocked", incident)
    job_id = await service.queue_fire(
        w.trigger.id,
        organization_id=w.ctx.organization_id,
        event_context="unconsumed private event",
    )
    job = await db.get(BackgroundJob, job_id)
    activation = UUID(job.payload["activation_id"])
    for failure in range(3):
        wait = await repo.get(db, activation)
        job = await db.get(BackgroundJob, wait.last_job_id)
        job.status = "dead"
        await db.flush()
        assert await service.resume_device_waits() == (1 if failure < 2 else 0)
    wait = await repo.get(db, activation)
    assert wait.status == "failed"
    assert wait.admission_failures == 3
    assert wait.event_context == "unconsumed private event"
    await db.refresh(w.trigger)
    assert not w.trigger.is_active
    assert await service.resume_device_waits() == 0
    incident.assert_awaited_once()


async def test_readiness_race_rolls_back_the_empty_run_but_keeps_the_committed_activation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.db.models.agent_run import AgentRun
    from app.db.models.background_job import BackgroundJob
    from app.repositories import agent_run_repo
    from app.services import agent_trigger as trigger_module
    from app.services.agent_runner import AgentRunnerService
    from app.services.agent_trigger import AgentTriggerService
    from app.services.routine_devices import RoutineDeviceOffline

    w = await world(db)
    trigger_id, agent_id, org_id = w.trigger.id, w.trigger.agent_id, w.ctx.organization_id
    ticket = datetime.now(UTC)
    w.trigger.fire_in_flight_since = ticket
    service = AgentTriggerService(db)
    job_id = await service.queue_fire(trigger_id, organization_id=org_id)
    job = await db.get(BackgroundJob, job_id)
    activation = UUID(job.payload["activation_id"])
    await db.commit()
    monkeypatch.setattr(service, "_creator_context", AsyncMock(return_value=w.ctx))
    monkeypatch.setattr(
        service.agents, "get", AsyncMock(return_value=await db.get(Agent, agent_id))
    )
    monkeypatch.setattr(service, "_run_log", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(trigger_module, "local_device_ready", AsyncMock(return_value=object()))

    async def fails_after_creating_uncommitted_run(*args: object, **kwargs: object) -> None:
        await agent_run_repo.create_run(
            db,
            organization_id=org_id,
            agent_id=agent_id,
            agent_version_id=None,
            user_id=w.ctx.user_id,
            conversation_id=None,
            surface="schedule",
            model_label=None,
            started_at=datetime.now(UTC),
            trigger_id=trigger_id,
        )
        raise RoutineDeviceOffline(message="disconnected during preparation")

    monkeypatch.setattr(
        AgentRunnerService, "execute", AsyncMock(side_effect=fails_after_creating_uncommitted_run)
    )
    await service.fire(trigger_id, activation_id=activation, claimed_at=ticket)
    assert await db.scalar(select(AgentRun.id).where(AgentRun.agent_id == agent_id)) is None
    assert (await repo.get(db, activation)).status == "waiting"
    assert (
        await agent_trigger_repo.get_by_id(db, trigger_id, fresh=True)
    ).fire_in_flight_since is None


async def test_an_old_permission_refusal_does_not_disable_the_reconfigured_routine(
    db: AsyncSession,
) -> None:
    from app.services.agent_trigger import AgentTriggerService

    w = await world(db, event=True)
    activation = await park(db, w, context="old private event")
    old_intent = activation_intent(w.trigger)
    w.trigger.prompt = "reconfigured responsibility"
    await db.flush()
    await AgentTriggerService(db)._block_local_activation(
        w.trigger.id, activation_id=activation, intent=old_intent, name="Old routine"
    )
    await db.refresh(w.trigger)
    assert w.trigger.is_active
    assert (await repo.get(db, activation)).status == "cancelled"
    assert (await repo.get(db, activation)).event_context is None
