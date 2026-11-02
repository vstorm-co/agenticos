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
