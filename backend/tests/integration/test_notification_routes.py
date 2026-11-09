"""Private channel opt-in, revocation and bounded provider submission on PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.channel_bot import ChannelBot
from app.db.models.channel_identity import ChannelIdentity
from app.db.models.channel_session import ChannelSession
from app.db.models.notification import (
    CHAT_NOTIFICATION_CHANNELS,
    NotificationChannel,
    NotificationEventType,
)
from app.db.models.notification_delivery import NotificationDelivery
from app.db.models.notification_route import NotificationRoute
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.teams_conversation import TeamsConversation
from app.db.models.user import User
from app.repositories import channel_identity_repo
from app.repositories import notification_route as route_repo
from app.schemas.notification_route import NotificationRouteUpdate
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import CLAIM_LEASE, NotificationDeliveryService
from app.services.notification_routes import NotificationRouteService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def person(db: AsyncSession) -> tuple[User, Organization, AuthContext]:
    user = User(id=uuid4(), email=f"{uuid4()}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(id=uuid4(), name="Acme", slug=uuid4().hex, created_by_user_id=user.id)
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    await db.flush()
    return user, org, AuthContext(user_id=user.id, organization_id=org.id, role="owner")


async def destination(
    db: AsyncSession,
    *,
    user: User,
    org: Organization,
    platform: str = "slack",
    chat_type: str = "private",
) -> tuple[ChannelSession, ChannelBot, ChannelIdentity]:
    identity = ChannelIdentity(
        id=uuid4(),
        platform=platform,
        platform_user_id=uuid4().hex,
        user_id=user.id,
        platform_display_name="Ada",
    )
    bot = ChannelBot(
        id=uuid4(),
        organization_id=org.id,
        platform=platform,
        name="Assistant",
        token_encrypted="sealed",
    )
    db.add_all([identity, bot])
    await db.flush()
    session = ChannelSession(
        id=uuid4(),
        bot_id=bot.id,
        identity_id=identity.id,
        platform_chat_id=uuid4().hex,
        chat_type=chat_type,
    )
    db.add(session)
    await db.flush()
    return session, bot, identity


async def queue(
    db: AsyncSession, ctx: AuthContext, *, context: dict[str, str] | None = None
) -> list[NotificationDelivery]:
    written = await NotificationCenterService(db).write(
        event_type=NotificationEventType.RUN_COMPLETED,
        occurrence_id=str(uuid4()),
        recipients=[ctx.subject_id],
        organization_id=ctx.organization_id,
        summary="Your routine finished",
        context_url="/runs",
        render_context=context,
    )
    result = await db.execute(
        select(NotificationDelivery).where(NotificationDelivery.notification_id == written[0].id)
    )
    return list(result.scalars().all())


@pytest.mark.parametrize("platform", sorted(CHAT_NOTIFICATION_CHANNELS))
async def test_linked_private_chat_requires_explicit_opt_in(
    db: AsyncSession, platform: str
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org, platform=platform)
    service = NotificationRouteService(db)
    listed = await service.list(ctx)
    assert listed.items == []
    assert listed.destinations[0].session_id == session.id
    assert all(row.channel != platform for row in await queue(db, ctx))
    saved = await service.replace(
        ctx, NotificationRouteUpdate(channel=platform, session_id=session.id)
    )
    assert saved.items[0].available
    rows = [row for row in await queue(db, ctx) if row.channel == platform]
    assert len(rows) == 1
    assert rows[0].route_id == saved.items[0].id


@pytest.mark.parametrize(
    "invalid",
    [
        "group",
        "other_user",
        "other_org",
        "unlinked",
        "inactive_identity",
        "inactive_session",
        "inactive_bot",
        "group_policy",
        "whitelist",
        "different_platform",
    ],
)
async def test_private_destination_refuses_ineligible_scope(db: AsyncSession, invalid: str) -> None:
    user, org, ctx = await person(db)
    session, bot, identity = await destination(db, user=user, org=org)
    if invalid == "group":
        session.chat_type = "group"
    elif invalid == "other_user":
        other, _, _ = await person(db)
        identity.user_id = other.id
    elif invalid == "other_org":
        _, other_org, _ = await person(db)
        bot.organization_id = other_org.id
    elif invalid == "unlinked":
        identity.user_id = None
    elif invalid == "inactive_identity":
        identity.is_active = False
    elif invalid == "inactive_session":
        session.is_active = False
    elif invalid == "inactive_bot":
        bot.is_active = False
    elif invalid == "group_policy":
        bot.access_policy = {"mode": "group_only", "allowed_groups": [session.platform_chat_id]}
    elif invalid == "whitelist":
        bot.access_policy = {"mode": "whitelist", "whitelist": ["someone_else"]}
    else:
        identity.platform = "telegram"
    await db.flush()
    service = NotificationRouteService(db)
    assert not (await service.list(ctx)).destinations
    with pytest.raises(NotFoundError):
        await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=session.id))


@pytest.mark.parametrize(
    "credential", ["key", "background", "fallback", "anonymous", "removed_member"]
)
async def test_only_a_current_human_member_can_route_notifications(
    db: AsyncSession, credential: str
) -> None:
    _, _, ctx = await person(db)
    if credential == "key":
        ctx = replace(ctx, api_key_id=uuid4())
    elif credential == "background":
        ctx = replace(ctx, routine_id=uuid4())
    elif credential == "fallback":
        ctx = replace(ctx, subject_is_publisher_fallback=True)
    elif credential == "anonymous":
        ctx = replace(ctx, user_id=None)
    else:
        await db.execute(
            delete(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
        )
    with pytest.raises(AuthorizationError):
        await NotificationRouteService(db).replace(
            ctx, NotificationRouteUpdate(channel="slack", session_id=None)
        )


@pytest.mark.parametrize(
    "change",
    ["replace", "revoke", "unlink_relink", "policy", "event_off", "membership", "deactivate"],
)
async def test_pending_delivery_rechecks_live_authority(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    user, org, ctx = await person(db)
    session, bot, identity = await destination(db, user=user, org=org)
    service = NotificationRouteService(db)
    await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=session.id))
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    await sweep.claim_and_advance(now=now)
    if change == "replace":
        other, _, _ = await destination(db, user=user, org=org)
        await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=other.id))
    elif change == "revoke":
        await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=None))
    elif change == "unlink_relink":
        await channel_identity_repo.update(db, db_identity=identity, update_data={"user_id": None})
        await channel_identity_repo.update(
            db, db_identity=identity, update_data={"user_id": user.id}
        )
    elif change == "policy":
        bot.access_policy = {"mode": "whitelist", "whitelist": []}
    elif change == "event_off":
        await NotificationCenterService(db).update_preference(
            ctx,
            event_type=NotificationEventType.RUN_COMPLETED,
            channel=NotificationChannel.SLACK,
            enabled=False,
        )
    elif change == "membership":
        await db.execute(delete(OrganizationMember).where(OrganizationMember.user_id == user.id))
    else:
        user.is_active = False
    await db.flush()
    send = AsyncMock()
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "skipped"
    send.assert_not_awaited()


async def test_chat_provider_failure_is_terminal_and_crash_is_not_replayed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    await sweep.claim_and_advance(now=now)
    send = AsyncMock(side_effect=TimeoutError("private provider URL must not be stored"))
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "failed"
    await db.refresh(delivery)
    assert delivery.status == "failed"
    assert "private provider URL" not in (delivery.last_error or "")
    crash = next(row for row in await queue(db, ctx) if row.channel == "slack")
    await sweep.claim_and_advance(now=now)
    assert crash.attempts == 1
    later = now + CLAIM_LEASE + timedelta(seconds=1)
    assert crash.id not in {row.id for row in await sweep.claim_and_advance(now=later)}
    assert await sweep.reap_exhausted(now=later) == 1
    await db.refresh(crash)
    assert crash.status == "failed"
    send.assert_awaited_once()


async def test_delivery_uses_a_single_frozen_route_and_preserves_approval_degradation(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    now = datetime.now(UTC)
    sweep = NotificationDeliveryService(db)
    await sweep.claim_and_advance(now=now)
    send = AsyncMock()
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "sent"
    assert send.await_args.kwargs == {"summary": "Your routine finished", "context_url": "/runs"}
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "lost_claim"
    # A settled claim cannot be sent a second time even with the same claim token.
    assert delivery.id not in {
        row.id for row in await sweep.claim_and_advance(now=now + CLAIM_LEASE)
    }


async def test_replacing_route_nulls_old_delivery_and_keeps_no_implicit_new_target(
    db: AsyncSession,
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    service = NotificationRouteService(db)
    first = await service.replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    second = await service.replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    await db.refresh(delivery)
    assert delivery.route_id is None
    assert first.items[0].id != second.items[0].id
    assert (
        await route_repo.current(
            db, route_id=first.items[0].id, organization_id=org.id, user_id=user.id, channel="slack"
        )
        is None
    )


async def test_route_constraints_and_owner_deletion(db: AsyncSession) -> None:
    user, org, ctx = await person(db)
    session, bot, identity = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                NotificationRoute(
                    organization_id=org.id,
                    user_id=user.id,
                    channel="slack",
                    session_id=session.id,
                    identity_generation=identity.authorization_generation,
                    bot_generation=bot.authorization_generation,
                )
            )
            await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                NotificationRoute(
                    organization_id=org.id,
                    user_id=user.id,
                    channel="group",
                    session_id=session.id,
                    identity_generation=identity.authorization_generation,
                    bot_generation=bot.authorization_generation,
                )
            )
            await db.flush()
    other, _, _ = await person(db)
    org.created_by_user_id = other.id
    await db.flush()
    await db.execute(delete(User).where(User.id == user.id))
    assert not await route_repo.routes(db, organization_id=org.id, user_ids=[user.id])


async def test_teams_reference_is_bound_to_org_bot_and_private_conversation(
    db: AsyncSession,
) -> None:
    user, org, _ = await person(db)
    _, bot, _ = await destination(db, user=user, org=org, platform="teams")
    ref = TeamsConversation(
        organization_id=org.id,
        bot_id=bot.id,
        key="private-key",
        conversation_id="original",
        service_url="https://smba.trafficmanager.net/emea/",
        conversation_type="personal",
    )
    db.add(ref)
    await db.flush()
    assert await route_repo.teams_reference(db, bot=bot, key=ref.key) is ref
    _, other_bot, _ = await destination(db, user=user, org=org, platform="teams")
    assert await route_repo.teams_reference(db, bot=other_bot, key=ref.key) is None
    ref.conversation_type = "groupChat"
    await db.flush()
    assert await route_repo.teams_reference(db, bot=bot, key=ref.key) is None


async def test_bot_reauthorization_invalidates_route_without_changing_its_session(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, ctx = await person(db)
    session, bot, _ = await destination(db, user=user, org=org)
    service = NotificationRouteService(db)
    await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=session.id))
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    now = datetime.now(UTC)
    sweep = NotificationDeliveryService(db)
    await sweep.claim_and_advance(now=now)
    bot.authorization_generation = uuid4()
    await db.flush()
    send = AsyncMock()
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert not (await service.list(ctx)).items[0].available
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "skipped"
    send.assert_not_awaited()


async def test_chat_approval_notice_drops_decision_link_after_demotion(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    notification = (
        await NotificationCenterService(db).write(
            recipients=[user.id],
            organization_id=org.id,
            event_type=NotificationEventType.APPROVAL_REQUESTED,
            occurrence_id=str(uuid4()),
            summary="Approve a tool",
            context_url="/approvals",
            render_context={"agent_name": "Assistant"},
        )
    )[0]
    result = await db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == notification.id,
            NotificationDelivery.channel == "slack",
        )
    )
    delivery = result.scalar_one()
    member = (
        await db.execute(select(OrganizationMember).where(OrganizationMember.user_id == user.id))
    ).scalar_one()
    member.role = "viewer"
    await db.flush()
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    await sweep.claim_and_advance(now=now)
    send = AsyncMock()
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "sent"
    assert send.await_args.kwargs == {
        "summary": "Assistant's run is held, waiting on an approval",
        "context_url": None,
    }


async def test_duplicate_claim_handoffs_cannot_submit_twice(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    now = datetime.now(UTC)
    await NotificationDeliveryService(db).claim_and_advance(now=now)
    await db.commit()
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    submissions = 0

    async def send(*args: object, **kwargs: object) -> None:
        nonlocal submissions
        submissions += 1
        entered.set()
        await release.wait()

    async def deliver() -> str:
        async with maker() as owned:
            result = await NotificationDeliveryService(owned).send_and_settle(
                delivery.id, claimed_at=now
            )
            await owned.commit()
            return result

    monkeypatch.setattr(NotificationRouteService, "_send", send)
    async with asyncio.TaskGroup() as tasks:
        original = tasks.create_task(deliver())
        await entered.wait()
        try:
            assert await deliver() == "lost_claim"
        finally:
            release.set()
    assert original.result() == "sent"
    assert submissions == 1


async def test_personal_export_includes_only_the_owners_route_metadata(db: AsyncSession) -> None:
    from app.services.personal_data import PersonalDataService

    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    other, other_org, other_ctx = await person(db)
    other_session, _, _ = await destination(db, user=other, org=other_org)
    await NotificationRouteService(db).replace(
        other_ctx, NotificationRouteUpdate(channel="slack", session_id=other_session.id)
    )
    exported = await PersonalDataService(db).export(user.id, actor_user_id=user.id)
    assert len(exported.notification_routes) == 1
    row = exported.notification_routes[0]
    assert row["organization_id"] == org.id
    assert row["session_id"] == session.id
    assert set(row) == {"id", "organization_id", "channel", "session_id", "created_at"}


async def test_a_configured_route_never_overrides_a_disabled_event_preference(
    db: AsyncSession,
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    await NotificationCenterService(db).update_preference(
        ctx,
        event_type=NotificationEventType.RUN_COMPLETED,
        channel=NotificationChannel.SLACK,
        enabled=False,
    )
    assert all(row.channel != "slack" for row in await queue(db, ctx))


async def test_an_older_selected_chat_is_not_misreported_as_unavailable(db: AsyncSession) -> None:
    user, org, ctx = await person(db)
    session, bot, identity = await destination(db, user=user, org=org)
    service = NotificationRouteService(db)
    await service.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=session.id))
    db.add_all(
        [
            ChannelSession(
                bot_id=bot.id,
                identity_id=identity.id,
                platform_chat_id=uuid4().hex,
                chat_type="private",
                last_message_at=datetime.now(UTC),
            )
            for _ in range(100)
        ]
    )
    await db.flush()
    result = await service.list(ctx)
    assert result.items[0].available
    assert session.id in {item.session_id for item in result.destinations}
    session.is_active = False
    await db.flush()
    result = await service.list(ctx)
    assert not result.items[0].available
    assert session.id not in {item.session_id for item in result.destinations}


async def test_confirmed_rate_limit_retries_after_its_delay_and_retires_the_old_handoff(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.channels.notification_send import NotificationRateLimited

    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    await sweep.claim_and_advance(now=now)
    send = AsyncMock(side_effect=[NotificationRateLimited(retry_after_seconds=30), None])
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "failed"
    await db.refresh(delivery)
    assert delivery.status == "pending" and delivery.retry_safe
    assert delivery.claimed_at is None
    assert delivery.claimed_until >= now + timedelta(seconds=30)
    assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "lost_claim"
    send.assert_awaited_once()
    assert delivery.id not in {
        row.id
        for row in await sweep.claim_and_advance(now=delivery.claimed_until - timedelta(seconds=1))
    }
    next_claim = delivery.claimed_until + timedelta(seconds=1)
    assert delivery.id in {row.id for row in await sweep.claim_and_advance(now=next_claim)}
    assert delivery.attempts == 2 and not delivery.retry_safe
    assert await sweep.send_and_settle(delivery.id, claimed_at=next_claim) == "sent"
    await db.refresh(delivery)
    assert delivery.status == "sent" and not delivery.retry_safe
    assert send.await_count == 2


@pytest.mark.parametrize("after_retry", ["uncertain", "crash", "revoked"])
async def test_a_safe_refusal_does_not_make_the_next_submission_replayable(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, after_retry: str
) -> None:
    from app.services.channels.notification_send import NotificationRateLimited

    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    routes = NotificationRouteService(db)
    await routes.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=session.id))
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    await sweep.claim_and_advance(now=now)
    send = AsyncMock(side_effect=NotificationRateLimited(retry_after_seconds=1))
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    await sweep.send_and_settle(delivery.id, claimed_at=now)
    await db.refresh(delivery)
    later = delivery.claimed_until + timedelta(seconds=1)
    if after_retry == "revoked":
        await routes.replace(ctx, NotificationRouteUpdate(channel="slack", session_id=None))
    await sweep.claim_and_advance(now=later)
    assert not delivery.retry_safe
    if after_retry == "crash":
        assert delivery.id not in {
            row.id
            for row in await sweep.claim_and_advance(now=later + CLAIM_LEASE + timedelta(seconds=1))
        }
        await sweep.reap_exhausted(now=later + CLAIM_LEASE + timedelta(seconds=1))
        await db.refresh(delivery)
        assert delivery.status == "failed"
    else:
        send.side_effect = TimeoutError("unconfirmed request")
        assert await sweep.send_and_settle(delivery.id, claimed_at=later) == (
            "skipped" if after_retry == "revoked" else "failed"
        )
        await db.refresh(delivery)
        assert delivery.status == ("skipped" if after_retry == "revoked" else "failed")
    assert send.await_count == (2 if after_retry == "uncertain" else 1)


async def test_repeated_confirmed_refusals_stop_after_five_claims(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.channels.notification_send import NotificationRateLimited

    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    sweep = NotificationDeliveryService(db)
    now = datetime.now(UTC)
    send = AsyncMock(side_effect=NotificationRateLimited(retry_after_seconds=1))
    monkeypatch.setattr(NotificationRouteService, "_send", send)
    for attempt in range(1, 6):
        assert delivery.id in {row.id for row in await sweep.claim_and_advance(now=now)}
        assert await sweep.send_and_settle(delivery.id, claimed_at=now) == "failed"
        await db.refresh(delivery)
        assert delivery.attempts == attempt
        assert delivery.status == ("pending" if attempt < 5 else "failed")
        now = max(now, delivery.claimed_until) + CLAIM_LEASE
    assert delivery.id not in {row.id for row in await sweep.claim_and_advance(now=now)}
    assert send.await_count == 5


@pytest.mark.parametrize("invalid", ["terminal", "old-handoff", "no-deadline"])
async def test_safe_retry_database_contract_refuses_ambiguous_states(
    db: AsyncSession, invalid: str
) -> None:
    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    delivery = next(row for row in await queue(db, ctx) if row.channel == "slack")
    delivery.retry_safe = True
    delivery.claimed_until = datetime.now(UTC) + timedelta(minutes=1)
    if invalid == "terminal":
        delivery.status = "sent"
    elif invalid == "old-handoff":
        delivery.claimed_at = datetime.now(UTC)
    else:
        delivery.claimed_until = None
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_acknowledgement_cancels_a_confirmed_refusal_waiting_for_retry_after(
    db: AsyncSession,
) -> None:
    from app.services.outcome import OutcomeService

    user, org, ctx = await person(db)
    session, _, _ = await destination(db, user=user, org=org)
    await NotificationRouteService(db).replace(
        ctx, NotificationRouteUpdate(channel="slack", session_id=session.id)
    )
    (note,) = await NotificationCenterService(db).write(
        event_type=NotificationEventType.RUN_FAILED,
        occurrence_id=uuid4().hex,
        recipients=[user.id],
        organization_id=org.id,
        summary="Routine needs attention",
        context_url="/routines",
        render_context={"cause": "routine-safe-refusal"},
    )
    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.notification_id == note.id, NotificationDelivery.channel == "slack"
        )
    )
    assert delivery is not None and note.outcome_id is not None
    delivery.retry_safe = True
    delivery.claimed_until = datetime.now(UTC) + timedelta(hours=1)
    delivery.attempts = 1
    await db.flush()
    await OutcomeService(db).settle(ctx, note.outcome_id, "acknowledge", via="chat")
    await db.refresh(delivery)
    assert delivery.status == "skipped" and not delivery.retry_safe
