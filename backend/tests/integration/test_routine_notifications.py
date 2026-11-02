"""Routine limits participate in the existing notification write and claimed-delivery paths."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.notification import Notification, NotificationChannel, NotificationEventType
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _routine(db: AsyncSession, selected: list[str] | None):
    user = User(email=f"{uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid4()}", created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    agent = Agent(
        organization_id=org.id, owner_user_id=user.id, name="Monitor", slug=f"monitor-{uuid4()}"
    )
    db.add_all([agent, OrganizationMember(organization_id=org.id, user_id=user.id, role="owner")])
    await db.flush()
    trigger = AgentTrigger(
        organization_id=org.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        prompt="Check",
        interval_seconds=300,
        next_fire_at=datetime.now(UTC),
        notification_channels=selected,
    )
    db.add(trigger)
    await db.flush()
    return user, org, trigger


@pytest.mark.parametrize(
    ("selected", "preference", "email"),
    [
        (None, True, True),
        ([], True, False),
        (["email"], True, True),
        (["push"], True, False),
        (["email", "push"], False, False),
    ],
)
async def test_routine_overrides_only_narrow_the_persons_preferences(
    db: AsyncSession, selected, preference, email
):
    user, org, trigger = await _routine(db, selected)
    db.add(
        NotificationChannelPreference(
            user_id=user.id, event_type="run_completed", channel="email", enabled=preference
        )
    )
    await db.flush()
    rows = await NotificationCenterService(db).write(
        recipients=[user.id],
        event_type=NotificationEventType.RUN_COMPLETED,
        occurrence_id=str(uuid4()),
        summary="A requested report",
        organization_id=org.id,
        render_context={"routine_origin_id": str(trigger.id), "routine_kind": "trigger"},
    )
    assert len(rows) == 1 and rows[0].in_app_visible
    deliveries = list(
        (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == rows[0].id
                )
            )
        ).all()
    )
    assert bool(deliveries) == email
    assert all(item.channel == NotificationChannel.EMAIL for item in deliveries)


@pytest.mark.parametrize("change", ["disabled", "paused", "deleted"])
async def test_a_claimed_delivery_rechecks_routine_limits_before_sending(
    db: AsyncSession, change: str
):
    user, org, trigger = await _routine(db, None)
    now = datetime.now(UTC)
    notification = Notification(
        organization_id=org.id,
        recipient_user_id=user.id,
        event_type="run_completed",
        occurrence_id=str(uuid4()),
        summary="Report",
        render_context={"routine_origin_id": str(trigger.id), "routine_kind": "trigger"},
    )
    db.add(notification)
    await db.flush()
    delivery = NotificationDelivery(
        notification_id=notification.id, channel="email", claimed_at=now, attempts=1
    )
    db.add(delivery)
    await db.flush()
    if change == "disabled":
        trigger.notification_channels = []
    elif change == "paused":
        trigger.is_active = False
    else:
        await db.delete(trigger)
    await db.flush()
    with patch("app.services.notification_delivery.get_email_service", new=AsyncMock()) as provider:
        assert (
            await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)
            == "skipped"
        )
    provider.assert_not_called()
    await db.refresh(delivery)
    assert delivery.status == "skipped"


async def test_routine_channel_limits_cannot_suppress_mandatory_security_events(db: AsyncSession):
    user, org, trigger = await _routine(db, [])
    with patch(
        "app.services.notification_center.routine_channels",
        new=AsyncMock(side_effect=AssertionError("Mandatory events must bypass routine policy")),
    ):
        rows = await NotificationCenterService(db).write(
            recipients=[user.id],
            event_type=NotificationEventType.SECURITY_EVENT,
            occurrence_id=str(uuid4()),
            summary="Security response",
            organization_id=org.id,
            render_context={"routine_origin_id": str(trigger.id), "routine_kind": "trigger"},
        )
    assert len(rows) == 1 and rows[0].in_app_visible
    deliveries = list(
        (
            await db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == rows[0].id
                )
            )
        ).all()
    )
    assert any(item.channel == "email" for item in deliveries)


async def test_report_activation_is_monotonic_atomic_and_rolls_back_with_results(db: AsyncSession):
    import asyncio
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.models.mcp_connection import McpConnection
    from app.db.models.watch import Watch
    from app.repositories import watch_repo

    user, org, trigger = await _routine(db, None)
    connection = McpConnection(
        user_id=user.id,
        scope="user",
        purpose="mcp",
        name="GitHub",
        catalog_key="github",
        url="https://github.example/mcp",
    )
    db.add(connection)
    await db.flush()
    tick = datetime.now(UTC)
    watch = Watch(
        organization_id=org.id,
        user_id=user.id,
        connection_id=connection.id,
        agent_id=trigger.agent_id,
        approved_sources={},
        title="Report",
        instructions="Check",
        interval_minutes=60,
        next_run_at=tick,
        report_mode="every_check",
    )
    db.add(watch)
    await db.flush()
    watch_id = watch.id
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def claim():
        async with sessions() as session, session.begin():
            return await watch_repo.claim_report_activation(
                session, watch_id=watch_id, scheduled_for=tick
            )

    assert sorted(await asyncio.gather(claim(), claim())) == [False, True]
    assert not await watch_repo.claim_report_activation(
        db, watch_id=watch_id, scheduled_for=tick - timedelta(seconds=1)
    )
    await db.refresh(watch)
    next_tick = tick + timedelta(hours=1)
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            assert await watch_repo.claim_report_activation(
                db, watch_id=watch_id, scheduled_for=next_tick
            )
            raise RuntimeError("Result write failed")
    assert watch.id == watch_id
    assert await watch_repo.claim_report_activation(db, watch_id=watch_id, scheduled_for=next_tick)


async def test_a_policy_query_failure_does_not_poison_result_writes_in_best_effort_mode(
    db: AsyncSession,
):
    from sqlalchemy import text

    user, org, trigger = await _routine(db, None)

    async def broken(*args, **kwargs):
        await db.execute(text("SELECT * FROM nonexistent_routine_policy_test_table"))

    with patch("app.services.notification_center.routine_channels", new=broken):
        rows = await NotificationCenterService(db).write(
            recipients=[user.id],
            event_type=NotificationEventType.RUN_COMPLETED,
            occurrence_id=str(uuid4()),
            summary="Report",
            organization_id=org.id,
            render_context={"routine_origin_id": str(trigger.id), "routine_kind": "trigger"},
            use_savepoint=True,
        )
    assert rows == []
    assert await db.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize(
    "selection,preference,email",
    [(None, True, True), ([], True, False), (None, False, False), (["email"], False, False)],
)
async def test_monthly_routine_budget_notices_share_one_case_and_honor_delivery_policy(
    db: AsyncSession,
    selection: list[str] | None,
    preference: bool,
    email: bool,
) -> None:
    from decimal import Decimal

    from app.db.models.outcome import Outcome
    from app.services.agent_trigger import AgentTriggerService
    from app.services.email.service import EmailKey
    from app.services.notifications import NotificationService

    user, org, trigger = await _routine(db, selection)
    user.notify_budget_alerts = preference
    trigger.monthly_budget_usd = Decimal("5")
    await db.flush()
    period = datetime(2026, 11, 1, tzinfo=UTC)
    arguments = {
        "organization_id": org.id,
        "owner_user_id": user.id,
        "routine_id": trigger.id,
        "routine_kind": "trigger",
        "name": "Daily digest",
        "limit": Decimal("5"),
        "period_start": period,
    }
    service = NotificationService(db)
    await service.routine_budget_paused(**arguments, spent=Decimal("5.10"))
    await service.routine_budget_paused(**arguments, spent=Decimal("6.00"))
    notes = list(await db.scalars(select(Notification)))
    assert len(notes) == 1
    note = notes[0]
    assert note.event_type == "budget_exceeded" and note.outcome_id is not None
    assert note.recipient_user_id == user.id and note.organization_id == org.id
    assert "Daily digest is waiting" in note.summary
    assert "$5.10 spent" in note.summary
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and case.source_run_id is None
    deliveries = list(await db.scalars(select(NotificationDelivery)))
    assert (len(deliveries) == 1) is email
    key, context = NotificationDeliveryService(db)._render(note, recipient=user, role="owner")
    assert key is EmailKey.NOTIFICATION
    assert context["summary"] == note.summary
    # There is no spend in this database: a raised/removed cap or fresh month can run again.
    assert not await AgentTriggerService(db)._stop_for_monthly_budget(trigger)
    await db.refresh(case)
    assert case.status == "resolved"
    for delivery in deliveries:
        await db.refresh(delivery)
        assert delivery.status == "skipped"


async def test_budget_alerts_without_routine_pause_metadata_keep_the_existing_rendering(
    db: AsyncSession,
) -> None:
    from app.services.email.service import EmailKey

    user, org, _ = await _routine(db, None)
    (note,) = await NotificationCenterService(db).write(
        recipients=[user.id],
        organization_id=org.id,
        event_type=NotificationEventType.BUDGET_EXCEEDED,
        occurrence_id=str(uuid4()),
        summary="A run hit its cap",
    )
    assert note.outcome_id is None
    key, _ = NotificationDeliveryService(db)._render(note, recipient=user, role="owner")
    assert key is EmailKey.BUDGET_EXCEEDED


async def test_a_new_month_opens_a_new_budget_case_but_never_notifies_an_inactive_owner(
    db: AsyncSession,
) -> None:
    from decimal import Decimal

    from app.services.notifications import NotificationService
    from app.services.outcome import OutcomeService

    user, org, trigger = await _routine(db, None)
    arguments = {
        "organization_id": org.id,
        "owner_user_id": user.id,
        "routine_id": trigger.id,
        "routine_kind": "trigger",
        "name": None,
        "limit": Decimal("5"),
        "spent": Decimal("5.10"),
    }
    service = NotificationService(db)
    await service.routine_budget_paused(**arguments, period_start=datetime(2026, 10, 1, tzinfo=UTC))
    await service.routine_budget_paused(**arguments, period_start=datetime(2026, 11, 1, tzinfo=UTC))
    notes = list(await db.scalars(select(Notification)))
    assert len(notes) == 2 and notes[0].outcome_id != notes[1].outcome_id
    await OutcomeService(db).resolve_routine_budget(
        organization_id=org.id, user_id=None, routine_id=trigger.id, routine_kind="trigger"
    )
    user.is_active = False
    await db.flush()
    await service.routine_budget_paused(**arguments, period_start=datetime(2026, 12, 1, tzinfo=UTC))
    await service.routine_budget_paused(
        **(arguments | {"owner_user_id": None}), period_start=datetime(2026, 12, 1, tzinfo=UTC)
    )
    assert len(list(await db.scalars(select(Notification)))) == 2


async def test_watch_budget_notices_stay_in_the_owners_scope_and_close_on_removal(
    db: AsyncSession,
) -> None:
    from decimal import Decimal

    from app.agents.spec import AgentSpec, PersonalMcpServerRef
    from app.core.permissions import AuthContext, OrgRoleName
    from app.db.models.mcp_connection import McpConnection
    from app.db.models.outcome import Outcome
    from app.db.models.watch import Watch
    from app.services.notifications import NotificationService
    from app.services.outcome import OutcomeService
    from app.services.watch_sources import approve_sources
    from app.services.watches import WatchService

    user, org, trigger = await _routine(db, None)
    connection = McpConnection(
        user_id=user.id,
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
        organization_id=org.id,
        user_id=user.id,
        connection_id=connection.id,
        agent_id=trigger.agent_id,
        approved_sources=sources.model_dump(mode="json"),
        title="Reviews",
        instructions="Look for reviews",
        interval_minutes=60,
        next_run_at=datetime.now(UTC),
        notification_channels=[],
    )
    db.add(watch)
    await db.flush()
    await NotificationService(db).routine_budget_paused(
        organization_id=org.id,
        owner_user_id=user.id,
        routine_id=watch.id,
        routine_kind="watch",
        name=watch.title,
        limit=Decimal("1"),
        spent=Decimal("1.10"),
        period_start=datetime(2026, 11, 1, tzinfo=UTC),
    )
    note = await db.scalar(select(Notification))
    assert note is not None and note.outcome_id is not None
    case = await db.get(Outcome, note.outcome_id)
    assert case is not None and case.status == "open"
    assert "Ask an administrator" in note.summary
    assert list(await db.scalars(select(NotificationDelivery))) == []
    await OutcomeService(db).resolve_routine_budget(
        organization_id=org.id, user_id=user.id, routine_id=watch.id, routine_kind="trigger"
    )
    await db.refresh(case)
    assert case.status == "open", "a trigger cannot close a watch's budget case"
    ctx = AuthContext(organization_id=org.id, user_id=user.id, role=OrgRoleName.OWNER)
    await WatchService(db).delete(ctx, watch.id)
    await db.refresh(case)
    assert case.status == "resolved"


async def test_changing_a_limit_reuses_the_monthly_case_and_respects_its_mute(
    db: AsyncSession,
) -> None:
    from decimal import Decimal

    from app.core.permissions import AuthContext, OrgRoleName
    from app.services.notifications import NotificationService
    from app.services.outcome import OutcomeService

    user, org, trigger = await _routine(db, None)
    arguments = {
        "organization_id": org.id,
        "owner_user_id": user.id,
        "routine_id": trigger.id,
        "routine_kind": "trigger",
        "name": "Digest",
        "period_start": datetime(2026, 11, 1, tzinfo=UTC),
    }
    service = NotificationService(db)
    for amount in ("5", "10"):
        await service.routine_budget_paused(
            **arguments, limit=Decimal(amount), spent=Decimal(amount)
        )
    notes = list(await db.scalars(select(Notification)))
    assert len(notes) == 2 and notes[0].outcome_id == notes[1].outcome_id
    assert notes[0].outcome_id is not None
    ctx = AuthContext(organization_id=org.id, user_id=user.id, role=OrgRoleName.OWNER)
    await OutcomeService(db).settle(ctx, notes[0].outcome_id, "mute", via="inbox")
    await service.routine_budget_paused(**arguments, limit=Decimal("15"), spent=Decimal("15"))
    latest = list(await db.scalars(select(Notification)))
    assert len(latest) == 3 and {note.outcome_id for note in latest} == {notes[0].outcome_id}
    assert all(note.dismissed_at is not None for note in latest)
    assert all(
        delivery.status == "skipped" for delivery in await db.scalars(select(NotificationDelivery))
    )
