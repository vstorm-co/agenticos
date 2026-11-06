"""Routine incidents share owner state and recover without replaying old alerts."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.conversation import Conversation
from app.db.models.notification import Notification
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.outcome import Outcome
from app.db.models.user import User
from app.db.models.watch import Watch
from app.repositories import agent_run_repo
from app.services.notifications import NotificationService
from app.services.outcome import OutcomeService

pytestmark = [pytest.mark.anyio, pytest.mark.security]
NOW = datetime(2026, 11, 2, 10, tzinfo=UTC)


@dataclass
class World:
    user: User
    org: Organization
    agent: Agent
    version: AgentVersion
    trigger: AgentTrigger
    chat: Conversation

    @property
    def ctx(self) -> AuthContext:
        return AuthContext(
            user_id=self.user.id, organization_id=self.org.id, role=OrgRoleName.OWNER
        )


@pytest.fixture
async def world(db: AsyncSession) -> World:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id, owner_user_id=user.id, name="Monitor", slug=f"a-{uuid.uuid4()}"
    )
    db.add_all([agent, OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")])
    await db.flush()
    version = AgentVersion(agent_id=agent.id, organization_id=org.id, version=1, spec={})
    chat = Conversation(organization_id=org.id, user_id=user.id, title="Routine log")
    db.add_all([version, chat])
    await db.flush()
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        name="Daily report",
        prompt="Report",
        interval_seconds=300,
        next_fire_at=NOW,
        conversation_id=chat.id,
    )
    db.add(trigger)
    await db.flush()
    return World(user, org, agent, version, trigger, chat)


async def result(db: AsyncSession, world: World, status: RunStatus, tick: int) -> AgentRun:
    at = NOW + timedelta(minutes=tick)
    run = await agent_run_repo.create_run(
        db,
        organization_id=world.org.id,
        agent_id=world.agent.id,
        agent_version_id=world.version.id,
        user_id=world.user.id,
        conversation_id=world.chat.id,
        surface=RunSurface.SCHEDULE.value,
        model_label="test",
        started_at=at - timedelta(seconds=30),
        trigger_id=world.trigger.id,
        routine_kind="trigger",
        routine_origin_id=world.trigger.id,
        initiated_by_publisher_fallback=True,
    )
    run.status, run.ended_at = status.value, at
    await db.flush()
    return run


async def notes(db: AsyncSession) -> list[Notification]:
    return list(
        await db.scalars(select(Notification).order_by(Notification.created_at, Notification.id))
    )


async def test_acknowledging_the_shared_case_does_not_reset_automatic_pause_policy(
    db: AsyncSession,
    world: World,
) -> None:
    from app.services.routine_health import RoutineHealthService

    health = RoutineHealthService(db)
    notifications = NotificationService(db)
    first = await result(db, world, RunStatus.FAILED, 1)
    # Runs using the publisher fallback still have a routine owner.
    first.user_id = None
    await health.run_result(first)
    await notifications.routine_result(first)
    (note,) = await notes(db)
    assert note.outcome_id is not None
    await OutcomeService(db).settle(world.ctx, note.outcome_id, "acknowledge", via="chat")
    for tick in (2, 3):
        failed = await result(db, world, RunStatus.FAILED, tick)
        await health.run_result(failed)
        await notifications.routine_result(failed)
    assert not world.trigger.is_active and world.trigger.consecutive_failures == 3
    assert world.trigger.auto_stopped_at is not None
    assert len(await notes(db)) == 1
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and case.status == "acknowledged"
    assert "Paused automatically" in case.summary


@pytest.mark.parametrize("limit", [1, 3])
async def test_automatic_pause_escalates_the_same_case_and_supersedes_the_old_notice(
    db: AsyncSession,
    world: World,
    limit: int,
) -> None:
    from app.db.models.notification_preference import NotificationChannelPreference
    from app.services.routine_health import RoutineHealthService
    from app.services.routine_notifications import allowed_channels

    world.trigger.max_failures = limit
    db.add(
        NotificationChannelPreference(
            user_id=world.user.id, event_type="run_failed", channel="email", enabled=True
        )
    )
    await db.flush()
    health, notifications = RoutineHealthService(db), NotificationService(db)
    for tick in range(1, limit + 1):
        failed = await result(db, world, RunStatus.FAILED, tick)
        await health.run_result(failed)
        await notifications.routine_result(failed)
    recorded = await notes(db)
    assert len(recorded) == (1 if limit == 1 else 2)
    current = next(note for note in recorded if "Paused automatically" in note.summary)
    assert current.outcome_id is not None
    assert all(note.outcome_id == current.outcome_id for note in recorded)
    assert "Paused automatically" in current.summary and not world.trigger.is_active
    assert current.render_context is not None
    assert (
        current.render_context["routine_auto_stopped_at"]
        == world.trigger.auto_stopped_at.isoformat()
    )
    assert (
        await allowed_channels(
            db,
            organization_id=world.org.id,
            recipient_user_id=world.user.id,
            context=current.render_context,
        )
        is None
    )
    deliveries = list(
        await db.scalars(
            select(NotificationDelivery).where(NotificationDelivery.notification_id == current.id)
        )
    )
    assert any(
        delivery.channel == "email" and delivery.status == "pending" for delivery in deliveries
    )
    if limit > 1:
        earlier = next(note for note in recorded if note.id != current.id)
        await db.refresh(earlier)
        assert earlier.dismissed_at is not None
        previous = list(
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == earlier.id
                )
            )
        )
        assert all(delivery.status == "skipped" for delivery in previous)
    await notifications.routine_result(failed)
    assert len(await notes(db)) == len(recorded)
    await OutcomeService(db).settle(world.ctx, current.outcome_id, "acknowledge", via="chat")
    for delivery in deliveries:
        await db.refresh(delivery)
        assert delivery.status == "skipped"
    assert not world.trigger.is_active


async def test_one_failure_episode_acknowledges_recovers_and_reopens_the_same_case(
    db: AsyncSession,
    world: World,
) -> None:
    service = NotificationService(db)
    first = await result(db, world, RunStatus.FAILED, 1)
    # The creator is notified even without granting personal account access to the run.
    first.user_id = None
    await db.flush()
    await service.run_failed(first, agent=world.agent, error="must-not-appear-in-alert")
    await service.routine_result(first)
    (note,) = await notes(db)
    assert note.outcome_id is not None and note.recipient_user_id == world.user.id
    assert "must-not-appear" not in note.summary
    case_id = note.outcome_id
    await OutcomeService(db).settle(world.ctx, case_id, "acknowledge", via="chat")
    await service.routine_result(await result(db, world, RunStatus.FAILED, 2))
    assert len(await notes(db)) == 1
    case = await db.get(Outcome, case_id)
    assert case is not None and case.status == "acknowledged"
    await service.routine_result(await result(db, world, RunStatus.COMPLETED, 3))
    await db.refresh(case)
    assert case.status == "resolved"
    await service.routine_result(await result(db, world, RunStatus.FAILED, 4))
    assert len(await notes(db)) == 2
    assert {note.outcome_id for note in await notes(db)} == {case_id}
    await db.refresh(case)
    assert case.status == "open"


async def test_muting_a_routine_failure_stays_muted_across_recovery(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    await service.routine_result(await result(db, world, RunStatus.FAILED, 1))
    (note,) = await notes(db)
    assert note.outcome_id is not None
    await OutcomeService(db).settle(world.ctx, note.outcome_id, "mute", via="inbox")
    await service.routine_result(await result(db, world, RunStatus.COMPLETED, 2))
    await service.routine_result(await result(db, world, RunStatus.FAILED, 3))
    assert len(await notes(db)) == 1
    deliveries = list(await db.scalars(select(NotificationDelivery)))
    assert deliveries and all(delivery.status == "skipped" for delivery in deliveries)


async def test_stale_callbacks_cannot_reopen_or_close_a_newer_routine_result(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    old_failure = await result(db, world, RunStatus.FAILED, 1)
    old_success = await result(db, world, RunStatus.COMPLETED, 2)
    await service.routine_result(old_success)
    await service.routine_result(old_failure)
    assert await notes(db) == []
    newer = await result(db, world, RunStatus.LOOP_STOPPED, 3)
    await service.routine_result(newer)
    await service.routine_result(old_success)
    (note,) = await notes(db)
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and case.status == "open"


@pytest.mark.parametrize(
    "status,label",
    [
        (RunStatus.BUDGET_EXCEEDED, "spending limit"),
        (RunStatus.GUARDRAIL_BLOCKED, "guardrail"),
        (RunStatus.LOOP_STOPPED, "did not finish"),
    ],
)
async def test_non_successful_terminal_reasons_are_explicit(
    db: AsyncSession, world: World, status: RunStatus, label: str
) -> None:
    run = await result(db, world, status, 1)
    run.error = "private-provider-credential"
    await db.flush()
    await NotificationService(db).routine_result(run)
    (note,) = await notes(db)
    assert label in note.summary and "private-provider" not in note.summary


async def test_incident_database_failure_does_not_poison_the_completed_run(
    db: AsyncSession, world: World
) -> None:
    run = await result(db, world, RunStatus.FAILED, 1)

    async def fail(_self: OutcomeService, **kwargs: object) -> None:
        await db.execute(text("SELECT 1 / 0"))

    with patch("app.services.notifications.OutcomeService.routine_failure_occurrence", new=fail):
        await NotificationService(db).routine_result(run)
    assert await db.scalar(text("SELECT 1")) == 1
    await db.refresh(run)
    assert run.status == "failed"
    assert await notes(db) == []


async def make_watch(db: AsyncSession, world: World) -> Watch:
    from app.agents.spec import AgentSpec, PersonalMcpServerRef
    from app.db.models.mcp_connection import McpConnection
    from app.services.watch_sources import approve_sources

    connection = McpConnection(
        user_id=world.user.id,
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
    )
    db.add(connection)
    await db.flush()
    sources = approve_sources(
        AgentSpec(
            name="Monitor",
            mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")],
        ),
        connection,
    )
    watch = Watch(
        organization_id=world.org.id,
        user_id=world.user.id,
        agent_id=world.agent.id,
        connection_id=connection.id,
        approved_sources=sources.model_dump(mode="json"),
        title="Reviews",
        instructions="Look for reviews",
        interval_minutes=60,
        next_run_at=NOW,
    )
    db.add(watch)
    await db.flush()
    return watch


async def test_watch_attempt_clocks_and_incidents_ignore_late_results(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.watch import WatchAttemptStatus
    from app.repositories import watch_repo

    watch = await make_watch(db, world)
    later = NOW + timedelta(minutes=2)
    assert await watch_repo.mark_ran(db, watch=watch, at=later)
    assert not await watch_repo.mark_attempt(
        db, watch=watch, at=NOW, status=WatchAttemptStatus.NOT_COMPLETED
    )
    assert (watch.last_attempt_at, watch.last_attempt_status, watch.last_run_at) == (
        later,
        "completed",
        later,
    )
    run = await result(db, world, RunStatus.FAILED, 3)
    run.trigger_id = None
    run.routine_kind, run.routine_origin_id = "watch", watch.id
    run.routine_policy, run.routine_activation_at = watch.approved_sources, NOW
    await db.flush()
    await NotificationService(db).routine_result(run)
    assert await notes(db) == []
    # A genuinely newer failure opens the existing watch cause, then a confirmed read recovers it.
    failure_at = NOW + timedelta(minutes=4)
    assert await watch_repo.mark_attempt(
        db, watch=watch, at=failure_at, status=WatchAttemptStatus.SOURCE_UNAVAILABLE
    )
    await NotificationService(db).watch_blocked(
        watch, WatchAttemptStatus.SOURCE_UNAVAILABLE, observed_at=failure_at
    )
    (note,) = await notes(db)
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and case.dedupe_key == f"run_failed:watch:{watch.id}"
    assert not await watch_repo.mark_ran(db, watch=watch, at=NOW + timedelta(minutes=3))
    assert watch.last_attempt_status == "source_unavailable"
    assert watch.last_run_at == NOW + timedelta(minutes=3)
    await OutcomeService(db).resolve_routine_failure(
        organization_id=world.org.id,
        user_id=world.user.id,
        routine_id=watch.id,
        routine_kind="watch",
        reason="check",
        recovered_at=NOW + timedelta(minutes=3),
    )
    await db.refresh(case)
    assert case.status == "open"
    run.status = "completed"
    await db.flush()
    await NotificationService(db).routine_result(run)
    await db.refresh(case)
    assert case.status == "open", "model completion alone does not prove a source reading"
    success_at = NOW + timedelta(minutes=5)
    assert await watch_repo.mark_ran(db, watch=watch, at=success_at)
    await OutcomeService(db).resolve_routine_failure(
        organization_id=world.org.id,
        user_id=world.user.id,
        routine_id=watch.id,
        routine_kind="watch",
        reason="check",
        recovered_at=success_at,
    )
    await db.refresh(case)
    assert case.status == "resolved"


async def test_retried_and_late_failures_cannot_undo_a_persons_resolution(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    run = await result(db, world, RunStatus.FAILED, 1)
    await service.routine_result(run)
    (note,) = await notes(db)
    assert note.outcome_id is not None
    await OutcomeService(db).settle(world.ctx, note.outcome_id, "resolve", via="inbox")
    await service.routine_result(run)
    late = await result(db, world, RunStatus.FAILED, 2)
    await service.routine_result(late)
    assert len(await notes(db)) == 1
    # This failure occurred after the decision, so it is a new incident.
    current = await result(db, world, RunStatus.FAILED, 3)
    current.ended_at = datetime.now(UTC) + timedelta(seconds=1)
    await db.flush()
    await service.routine_result(current)
    assert len(await notes(db)) == 2


async def test_native_budget_alert_and_incident_are_one_owner_delivery(
    db: AsyncSession, world: World
) -> None:
    from app.agents.capabilities.budget import BudgetScope
    from app.agents.spec import AgentSpec

    service = NotificationService(db)
    run = await result(db, world, RunStatus.BUDGET_EXCEEDED, 1)
    await service.budget_exceeded(
        run,
        agent=world.agent,
        spec=AgentSpec(name="Monitor"),
        reason="Monthly cap",
        scope=BudgetScope.AGENT,
    )
    await service.routine_result(run)
    owned = [note for note in await notes(db) if note.recipient_user_id == world.user.id]
    assert len(owned) == 1 and owned[0].event_type == "budget_exceeded"
    assert owned[0].outcome_id is not None
    case = await db.get(Outcome, owned[0].outcome_id)
    assert case is not None and case.kind == "run_failed"
    again = await result(db, world, RunStatus.BUDGET_EXCEEDED, 2)
    await service.budget_exceeded(
        again,
        agent=world.agent,
        spec=AgentSpec(name="Monitor"),
        reason="Monthly cap",
        scope=BudgetScope.AGENT,
    )
    await service.routine_result(again)
    assert len([note for note in await notes(db) if note.recipient_user_id == world.user.id]) == 1


async def test_a_parked_run_terminal_callback_reports_failure_under_its_original_routine(
    db: AsyncSession, world: World
) -> None:
    run = await result(db, world, RunStatus.AWAITING_APPROVAL, 1)
    service = NotificationService(db)
    await service.routine_result(run)
    assert await notes(db) == []
    run.status, run.ended_at = "failed", NOW + timedelta(minutes=2)
    await db.flush()
    await service.routine_result(run)
    (note,) = await notes(db)
    assert note.render_context is not None and note.render_context["run_id"] == str(run.id)
    assert note.render_context["routine_origin_id"] == str(world.trigger.id)


async def test_budget_opt_out_cannot_be_bypassed_by_a_generic_failure_alert(
    db: AsyncSession, world: World
) -> None:
    from app.agents.capabilities.budget import BudgetScope
    from app.agents.spec import AgentSpec
    from app.db.models.notification_preference import NotificationChannelPreference

    world.user.notify_budget_alerts = False
    for channel in ("in_app", "email", "push"):
        db.add(
            NotificationChannelPreference(
                user_id=world.user.id, event_type="budget_exceeded", channel=channel, enabled=False
            )
        )
    await db.flush()
    run = await result(db, world, RunStatus.BUDGET_EXCEEDED, 1)
    service = NotificationService(db)
    await service.budget_exceeded(
        run,
        agent=world.agent,
        spec=AgentSpec(name="Monitor"),
        reason="Run limit",
        scope=BudgetScope.RUN,
    )
    await service.routine_result(run)
    assert all(
        note.event_type == "budget_exceeded" and not note.in_app_visible for note in await notes(db)
    )
    assert list(await db.scalars(select(NotificationDelivery))) == []


async def test_failed_alert_write_keeps_a_new_incident_retryable(
    db: AsyncSession, world: World
) -> None:
    from app.services.notification_center import NotificationCenterService

    service = NotificationService(db)
    await service.routine_result(await result(db, world, RunStatus.FAILED, 1))
    await service.routine_result(await result(db, world, RunStatus.COMPLETED, 2))
    run = await result(db, world, RunStatus.FAILED, 3)
    original = NotificationCenterService.write

    async def fail(_self: NotificationCenterService, **kwargs: object) -> list[Notification]:
        await db.execute(text("SELECT 1 / 0"))
        return []

    with patch.object(NotificationCenterService, "write", new=fail):
        await service.routine_result(run)
    assert len(await notes(db)) == 1
    # A retry of that exact callback still admits its new notification.
    assert NotificationCenterService.write is original
    await service.routine_result(run)
    assert len(await notes(db)) == 2


async def test_removing_a_responsibility_closes_its_run_and_delivery_incidents(
    db: AsyncSession, world: World
) -> None:
    from unittest.mock import AsyncMock

    from app.services.agent_trigger import AgentTriggerService

    run = await result(db, world, RunStatus.FAILED, 1)
    await NotificationService(db).routine_result(run)
    await NotificationService(db).routine_blocked(
        organization_id=world.org.id,
        owner_user_id=world.user.id,
        routine_id=world.trigger.id,
        routine_kind="trigger",
        reason="delivery",
        name="Report",
        detail="Chat unavailable",
        observed_at=NOW + timedelta(minutes=2),
        run=run,
    )
    cases = list(await db.scalars(select(Outcome)))
    assert len(cases) == 2
    with patch("app.services.agent_trigger.record_audit", new=AsyncMock()):
        await AgentTriggerService(db).delete(world.ctx, world.agent.id, world.trigger.id)
    for case in cases:
        await db.refresh(case)
        assert case.status == "resolved"
    assert all(
        delivery.status == "skipped" for delivery in await db.scalars(select(NotificationDelivery))
    )


@pytest.mark.parametrize(
    "change", ["inactive", "paused", "missing", "ownerless", "clockless", "foreign", "other-actor"]
)
async def test_ineligible_or_unordered_results_do_not_create_owner_incidents(
    db: AsyncSession, world: World, change: str
) -> None:
    run = await result(db, world, RunStatus.FAILED, 1)
    if change == "other-actor":
        other_user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
        db.add(other_user)
        await db.flush()
        run.user_id = other_user.id
    elif change == "inactive":
        world.user.is_active = False
    elif change == "paused":
        world.trigger.is_active = False
    elif change == "ownerless":
        world.trigger.created_by_user_id = None
    elif change == "clockless":
        run.started_at = run.ended_at = None
    elif change == "missing":
        run.routine_origin_id = uuid.uuid4()
    else:
        other = Organization(
            name="Other", slug=f"other-{uuid.uuid4()}", created_by_user_id=world.user.id
        )
        db.add(other)
        await db.flush()
        run.organization_id = other.id
    await db.flush()
    await NotificationService(db).routine_result(run)
    assert await notes(db) == []


async def test_stale_budget_callback_does_not_open_a_recovered_routine_incident(
    db: AsyncSession, world: World
) -> None:
    from app.agents.capabilities.budget import BudgetScope
    from app.agents.spec import AgentSpec

    old = await result(db, world, RunStatus.BUDGET_EXCEEDED, 1)
    await result(db, world, RunStatus.COMPLETED, 2)
    service = NotificationService(db)
    recipients = await service.budget_exceeded(
        old,
        agent=world.agent,
        spec=AgentSpec(name="Monitor"),
        reason="Old cap",
        scope=BudgetScope.ORGANIZATION,
    )
    await service.routine_result(old, budget_recipients=recipients)
    historical = await notes(db)
    assert len(historical) == 1 and historical[0].outcome_id is None
    assert list(await db.scalars(select(Outcome))) == []


async def test_continuing_incident_keeps_its_latest_reason_and_run_without_another_alert(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    await service.routine_result(await result(db, world, RunStatus.FAILED, 1))
    newer = await result(db, world, RunStatus.GUARDRAIL_BLOCKED, 2)
    await service.routine_result(newer)
    (note,) = await notes(db)
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and "guardrail" in case.summary
    assert case.source_run_id == newer.id
    assert case.last_observed_at == newer.ended_at


async def test_budget_escalation_keeps_other_administrators_separate_from_the_owner_case(
    db: AsyncSession, world: World
) -> None:
    from app.agents.capabilities.budget import BudgetScope
    from app.agents.spec import AgentSpec

    admin = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(admin)
    await db.flush()
    db.add(OrganizationMember(organization_id=world.org.id, user_id=admin.id, role="admin"))
    await db.flush()
    service = NotificationService(db)
    for tick in (1, 2):
        run = await result(db, world, RunStatus.BUDGET_EXCEEDED, tick)
        recipients = await service.budget_exceeded(
            run,
            agent=world.agent,
            spec=AgentSpec(name="Monitor"),
            reason="Organization cap",
            scope=BudgetScope.ORGANIZATION,
        )
        await service.routine_result(run, budget_recipients=recipients)
    all_notes = await notes(db)
    owner_notes = [note for note in all_notes if note.recipient_user_id == world.user.id]
    admin_notes = [note for note in all_notes if note.recipient_user_id == admin.id]
    assert len(owner_notes) == 3
    assert len([note for note in owner_notes if note.outcome_id is not None]) == 1
    owner_sends = list(
        await db.scalars(
            select(NotificationDelivery)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(Notification.recipient_user_id == world.user.id)
        )
    )
    assert len(owner_sends) == 2, (
        "financial notices are preserved without a duplicate failure email"
    )
    assert len(admin_notes) == 2 and all(note.outcome_id is None for note in admin_notes)


async def test_concurrent_terminal_callbacks_create_only_one_incident_and_alert(
    db: AsyncSession, world: World
) -> None:
    import asyncio

    run = await result(db, world, RunStatus.FAILED, 1)
    identifier = run.id
    await db.commit()
    assert db.bind is not None

    async def report() -> None:
        async with AsyncSession(db.bind, expire_on_commit=False) as session:
            current = await session.get(AgentRun, identifier)
            assert current is not None
            await NotificationService(session).routine_result(current)
            await session.commit()

    await asyncio.gather(report(), report())
    assert len(await notes(db)) == 1
    assert len(list(await db.scalars(select(Outcome)))) == 1


async def test_a_paused_or_ended_routine_cannot_deliver_a_completed_answer(
    db: AsyncSession, world: World
) -> None:
    from app.services.agent_trigger import AgentTriggerService

    run = await result(db, world, RunStatus.COMPLETED, 1)
    world.trigger.answer_to = "conversation"
    world.trigger.delivery_conversation_id = world.chat.id
    world.trigger.is_active = False
    await db.flush()
    delivery = await AgentTriggerService(db)._deliver(
        world.trigger, agent=world.agent, run=run, answer="Answer"
    )
    assert delivery.status == "unavailable"
    world.trigger.is_active = True
    world.trigger.ends_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.flush()
    delivery = await AgentTriggerService(db)._deliver(
        world.trigger, agent=world.agent, run=run, answer="Answer"
    )
    assert delivery.status == "unavailable"


async def test_resolved_incidents_without_a_settlement_time_require_repair(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    await service.routine_result(await result(db, world, RunStatus.FAILED, 1))
    (note,) = await notes(db)
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None
    case.status, case.settled_at = "resolved", None
    await db.flush()
    with pytest.raises(AssertionError, match="settlement time"):
        await service.routine_result(await result(db, world, RunStatus.FAILED, 2))


async def test_incident_evidence_and_recovery_clocks_never_move_backward(
    db: AsyncSession, world: World
) -> None:
    from app.repositories import outcome_repo

    service = NotificationService(db)
    run = await result(db, world, RunStatus.FAILED, 3)
    await service.routine_result(run)
    (note,) = await notes(db)
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None
    summary = case.summary
    await outcome_repo.observe_failure(db, outcome=case, at=NOW, run_id=None, summary="Old reason")
    assert case.last_observed_at == run.ended_at and case.summary == summary
    await OutcomeService(db).resolve_routine_failure(
        organization_id=world.org.id,
        user_id=None,
        routine_id=world.trigger.id,
        routine_kind="trigger",
        reason="run",
    )
    assert case.status == "open"
    success = await result(db, world, RunStatus.COMPLETED, 4)
    await service.routine_result(success)
    await db.refresh(case)
    settled = case.settled_at
    await service.routine_result(await result(db, world, RunStatus.COMPLETED, 5))
    await outcome_repo.observe_recovery(db, outcome=case, at=NOW)
    await db.refresh(case)
    assert case.last_recovered_at == NOW + timedelta(minutes=5)
    assert case.settled_at == settled and case.status == "resolved"


async def test_a_removed_watch_cannot_record_another_attempt(
    db: AsyncSession, world: World
) -> None:
    from app.db.models.watch import WatchAttemptStatus
    from app.repositories import watch_repo

    watch = await make_watch(db, world)
    await db.delete(watch)
    await db.flush()
    assert not await watch_repo.mark_attempt(
        db, watch=watch, at=NOW, status=WatchAttemptStatus.NOT_COMPLETED
    )


async def test_terminal_lookup_stays_in_its_organization(db: AsyncSession, world: World) -> None:
    run = await result(db, world, RunStatus.FAILED, 1)
    assert (
        await agent_run_repo.latest_terminal_for_trigger(
            db, organization_id=world.org.id, trigger_id=world.trigger.id
        )
        == run.id
    )
    assert (
        await agent_run_repo.latest_terminal_for_trigger(
            db, organization_id=uuid.uuid4(), trigger_id=world.trigger.id
        )
        is None
    )


async def test_a_late_old_run_and_delegated_children_cannot_change_root_health(
    db: AsyncSession, world: World
) -> None:
    service = NotificationService(db)
    old = await result(db, world, RunStatus.FAILED, 1)
    fresh = await result(db, world, RunStatus.COMPLETED, 2)
    old.ended_at = NOW + timedelta(minutes=5)
    await db.flush()
    await service.routine_result(fresh)
    await service.routine_result(old)
    assert await notes(db) == []
    child = await result(db, world, RunStatus.FAILED, 6)
    child.parent_run_id = fresh.id
    await db.flush()
    await service.routine_result(child)
    assert await notes(db) == []
    assert (
        await agent_run_repo.latest_terminal_for_trigger(
            db, organization_id=world.org.id, trigger_id=world.trigger.id
        )
        == fresh.id
    )


@pytest.mark.parametrize("notification_fails", [False, True])
async def test_a_reaped_native_run_reports_its_owner_incident(
    db: AsyncSession,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    notification_fails: bool,
) -> None:
    from app.services import run_reaper
    from app.services.run_reaper import RunReaperService

    monkeypatch.setattr(run_reaper.settings, "STALE_RUN_REAPED_AFTER_SECONDS", 1)
    run = await result(db, world, RunStatus.RUNNING, 1)
    run.started_at = datetime.now(UTC) - timedelta(hours=1)
    run.ended_at = None
    run.heartbeat_at = run.started_at
    await db.flush()
    # The rescue cutoff also includes the last row transition.
    from sqlalchemy import update

    await db.execute(
        update(AgentRun)
        .where(AgentRun.id == run.id)
        .values(updated_at=run.started_at)
        .execution_options(synchronize_session=False)
    )
    if notification_fails:

        async def broken_notification(self: NotificationService, run: AgentRun) -> None:
            await self.db.execute(text("select 1 / 0"))

        monkeypatch.setattr(NotificationService, "routine_result", broken_notification)
    events = await RunReaperService(db).reap_stale()
    assert len(events) == 1
    notices = await notes(db)
    if notification_fails:
        assert notices == []
    else:
        (note,) = notices
        assert note.outcome_id is not None and note.recipient_user_id == world.user.id
    await db.refresh(run)
    assert run.status == "failed"


@pytest.mark.parametrize("kind", ["trigger", "watch"])
@pytest.mark.parametrize("active", [True, False])
async def test_end_cleanup_ignores_cadence_and_pause(
    db: AsyncSession, world: World, kind: str, active: bool
) -> None:
    from app.services.agent_trigger import AgentTriggerService
    from app.services.proactive._watch import WatchLook

    routine = world.trigger if kind == "trigger" else await make_watch(db, world)
    routine.ends_at = NOW
    routine.is_active = active
    if isinstance(routine, Watch):
        routine.next_run_at = NOW + timedelta(days=30)
    else:
        routine.next_fire_at = NOW + timedelta(days=30)
    await NotificationService(db).routine_blocked(
        organization_id=world.org.id,
        owner_user_id=world.user.id,
        routine_id=routine.id,
        routine_kind="trigger" if kind == "trigger" else "watch",
        reason="delivery",
        name="Report",
        detail="The chat is unavailable.",
        observed_at=NOW - timedelta(minutes=1),
    )
    routine_id = routine.id
    await db.commit()
    # The minute worker resumes from persisted deadlines, not its previous process.
    db.expunge_all()
    if kind == "trigger":
        assert await AgentTriggerService(db).expire_due(now=NOW) == 1
    else:
        assert await WatchLook(db).expire_due(now=NOW) == 1
    await db.commit()
    routine = await db.get(AgentTrigger if kind == "trigger" else Watch, routine_id)
    assert routine is not None
    assert routine.is_active is False
    assert routine.end_settled_at == NOW
    outcomes = list(await db.scalars(select(Outcome)))
    assert outcomes and all(case.status == "resolved" for case in outcomes)
    assert all(note.dismissed_at is not None for note in await notes(db))
    if kind == "trigger":
        assert await AgentTriggerService(db).expire_due(now=NOW) == 0
    else:
        assert await WatchLook(db).expire_due(now=NOW) == 0


@pytest.mark.parametrize("kind", ["trigger", "watch"])
async def test_end_change_rearms_cleanup_without_ending_a_future_routine(
    db: AsyncSession, world: World, kind: str
) -> None:
    from app.services.agent_trigger import AgentTriggerService
    from app.services.proactive._watch import WatchLook

    routine = world.trigger if kind == "trigger" else await make_watch(db, world)
    service = AgentTriggerService(db) if kind == "trigger" else WatchLook(db)
    routine.ends_at = NOW
    await db.flush()
    assert await service.expire_due(now=NOW - timedelta(seconds=1)) == 0
    assert routine.is_active is True
    assert await service.expire_due(now=NOW) == 1
    routine.ends_at = NOW + timedelta(days=1)
    routine.is_active = True
    await db.flush()
    assert await service.expire_due(now=NOW) == 0
    assert routine.is_active is True
    assert await service.expire_due(now=NOW + timedelta(days=1)) == 1
    assert routine.end_settled_at == routine.ends_at


@pytest.mark.parametrize("kind", ["trigger", "watch"])
async def test_deadline_claim_survives_restart_and_skips_a_live_worker_lock(
    db: AsyncSession, engine: AsyncEngine, world: World, kind: str
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.repositories import agent_trigger_repo, watch_repo

    routine = world.trigger if kind == "trigger" else await make_watch(db, world)
    routine.ends_at = NOW
    await db.commit()
    repository = agent_trigger_repo if kind == "trigger" else watch_repo
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as first, sessions() as second:
        claimed = await repository.claim_ended(first, now=NOW, limit=1)
        assert [row.id for row in claimed] == [routine.id]
        assert await repository.claim_ended(second, now=NOW, limit=1) == []
        await second.rollback()
        await first.rollback()
        # A crashed transaction leaves no consumed deadline marker.
        reclaimed = await repository.claim_ended(second, now=NOW, limit=1)
        assert [row.id for row in reclaimed] == [routine.id]


async def test_watch_authority_does_not_follow_reauthorized_account_or_new_review(
    db: AsyncSession, world: World
) -> None:
    from dataclasses import replace

    from app.agents.spec import AgentSpec, PersonalMcpServerRef
    from app.core.exceptions import AuthorizationError
    from app.db.models.mcp_connection import McpConnection
    from app.services.routine_authority import RoutineAuthority
    from app.services.watch_sources import approve_sources

    world.org.proactive_watches_enabled = True
    world.agent.status = "published"
    world.agent.current_version_id = world.version.id
    watch = await make_watch(db, world)
    ctx = replace(world.ctx, routine_id=watch.id, routine_kind="watch", fired_as_creator="schedule")
    await db.flush()
    admitted = await RoutineAuthority.capture(db, ctx, agent_id=world.agent.id, run=None)
    assert admitted is not None
    connection = await db.get(McpConnection, watch.connection_id)
    assert connection is not None
    old_generation = connection.authorization_generation
    connection.authorization_generation = uuid.uuid4()
    await db.flush()
    with pytest.raises(AuthorizationError):
        await admitted.check_in(db, world.agent.id)
    # Re-review belongs to later runs; an old parked run cannot borrow it.
    spec = AgentSpec(
        name="Monitor", mcp_servers=[PersonalMcpServerRef(account="personal", catalog_key="github")]
    )
    watch.approved_sources = approve_sources(spec, connection).model_dump(mode="json")
    await db.flush()
    with pytest.raises(AuthorizationError):
        await admitted.check_in(db, world.agent.id)
    renewed = await RoutineAuthority.capture(db, ctx, agent_id=world.agent.id, run=None)
    assert renewed is not None and renewed.sources is not None
    assert renewed.sources.authorization_generation != old_generation
    # Old stored JSON remains renderable but cannot mint a guessed identity.
    watch.approved_sources = {
        key: value
        for key, value in watch.approved_sources.items()
        if key != "authorization_generation"
    }
    await db.flush()
    with pytest.raises(AuthorizationError):
        await RoutineAuthority.capture(db, ctx, agent_id=world.agent.id, run=None)


@pytest.mark.parametrize("other_account", [False, True])
async def test_watch_mcp_origin_must_be_its_approved_source(
    db: AsyncSession, world: World, other_account: bool
) -> None:
    import hashlib
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from pydantic_ai.tools import ToolDefinition

    from app.agents.mcp import MCP_ORIGIN, McpSourceIdentity, McpToolOrigin
    from app.agents.spec import AgentSpec
    from app.core.exceptions import AuthorizationError
    from app.db.models.mcp_connection import McpConnection
    from app.services.routine_authority import RoutineAuthority

    world.org.proactive_watches_enabled = True
    watch = await make_watch(db, world)
    await db.flush()
    ctx = replace(world.ctx, routine_id=watch.id, routine_kind="watch", fired_as_creator="schedule")
    authority = await RoutineAuthority.capture(db, ctx, agent_id=world.agent.id, run=None)
    assert authority is not None
    connection = await db.get(McpConnection, watch.connection_id)
    assert connection is not None
    tool = ToolDefinition(
        name="github_read",
        metadata={
            MCP_ORIGIN: McpToolOrigin(
                connection_id=uuid.uuid4() if other_account else connection.id,
                identity=McpSourceIdentity(
                    endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                    authorization_generation=connection.authorization_generation,
                    tool_prefix="github",
                ),
                tool_id="read",
            ),
            "annotations": {"readOnlyHint": True},
        },
    )

    @asynccontextmanager
    async def context() -> AsyncIterator[AsyncSession]:
        yield db

    with patch("app.services.routine_authority.get_db_context", new=context):
        if other_account:
            with pytest.raises(AuthorizationError):
                await authority.action_policy(world.agent.id, AgentSpec(name="Monitor"), tool)
        else:
            assert not (
                await authority.action_policy(world.agent.id, AgentSpec(name="Monitor"), tool)
            ).required
