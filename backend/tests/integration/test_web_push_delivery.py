"""Web Push against a real database (#2097): who gets a push delivery, how the
sweep settles one, and the two writes whose correctness is SQL - the signing
key claimed once, and a browser's subscription following whoever is signed in.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.db.models.apns_device import ApnsDevice
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.push_subscription import PushSubscription
from app.db.models.user import User
from app.repositories import apns_device as device_repo
from app.repositories import deployment_settings as deployment_repo
from app.repositories import push_subscription as push_repo
from app.services.notification_center import NotificationCenterService
from app.services.notification_delivery import NotificationDeliveryService
from app.services.web_push import PushOutcome

pytestmark = pytest.mark.anyio

ENDPOINT = "https://fcm.googleapis.com/fcm/send/"


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org_with_member(db) -> tuple[Organization, User]:
    owner = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    member = await _user(db)
    for user, role in ((owner, "owner"), (member, "member")):
        db.add(
            OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role)
        )
    await db.flush()
    return org, member


async def _subscribe(db, user: User) -> None:
    await push_repo.upsert(
        db,
        user_id=user.id,
        endpoint=ENDPOINT + uuid.uuid4().hex,
        p256dh="BPk",
        auth="c2Vj",
        user_agent="Chrome",
    )


async def _channels(db, notification_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(NotificationDelivery.channel).where(
            NotificationDelivery.notification_id == notification_id
        )
    )
    return sorted(rows.scalars().all())


async def _write(db, recipient: User, org: Organization, event: NotificationEventType, **kwargs):
    [notification] = await NotificationCenterService(db).write(
        recipients=[recipient.id],
        event_type=event,
        occurrence_id=uuid.uuid4().hex,
        summary="Your run finished",
        context_url="/runs?run=r1",
        organization_id=org.id,
        **kwargs,
    )
    return notification


class TestWhoIsPushedTo:
    async def test_a_subscribed_recipient_gets_a_push_delivery_beside_the_email(self, db):
        org, member = await _org_with_member(db)
        await _subscribe(db, member)
        notification = await _write(db, member, org, NotificationEventType.RUN_COMPLETED)
        assert await _channels(db, notification.id) == ["email", "push"]

    async def test_nobody_without_a_browser_is_queued_a_push(self, db):
        org, member = await _org_with_member(db)
        notification = await _write(db, member, org, NotificationEventType.RUN_COMPLETED)
        assert await _channels(db, notification.id) == ["email"]

    async def test_push_turned_off_for_an_event_queues_none(self, db):
        org, member = await _org_with_member(db)
        await _subscribe(db, member)
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=member.id,
                event_type=NotificationEventType.RUN_COMPLETED.value,
                channel="push",
                enabled=False,
            )
        )
        await db.flush()
        notification = await _write(
            db, member, org, NotificationEventType.RUN_COMPLETED, use_savepoint=True
        )
        assert await _channels(db, notification.id) == ["email"]

    async def test_a_sender_narrowing_to_email_queues_no_push(self, db):
        org, member = await _org_with_member(db)
        await _subscribe(db, member)
        notification = await _write(
            db,
            member,
            org,
            NotificationEventType.RUN_COMPLETED,
            channels={NotificationChannel.EMAIL},
        )
        assert await _channels(db, notification.id) == ["email"]

    async def test_a_mandatory_event_is_pushed_whatever_the_preference(self, db):
        org, member = await _org_with_member(db)
        await _subscribe(db, member)
        notification = await _write(
            db, member, org, NotificationEventType.SECURITY_EVENT, use_savepoint=True
        )
        assert "push" in await _channels(db, notification.id)

    async def test_a_failed_read_costs_a_mandatory_event_only_its_push(self, db):
        org, member = await _org_with_member(db)
        await _subscribe(db, member)
        with patch(
            "app.services.notification_center.PushService.subscribed",
            new=AsyncMock(side_effect=OSError("read failed")),
        ):
            notification = await _write(
                db, member, org, NotificationEventType.SECURITY_EVENT, use_savepoint=True
            )
        assert "push" not in await _channels(db, notification.id)

    async def test_a_failed_read_still_abandons_an_ordinary_event(self, db):
        org, member = await _org_with_member(db)
        with patch(
            "app.services.notification_center.PushService.subscribed",
            new=AsyncMock(side_effect=OSError("read failed")),
        ):
            written = await NotificationCenterService(db).write(
                recipients=[member.id],
                event_type=NotificationEventType.RUN_COMPLETED,
                occurrence_id=uuid.uuid4().hex,
                summary="Your run finished",
                organization_id=org.id,
                use_savepoint=True,
            )
        assert written == []


async def _queued_push(
    db, member: User, org: Organization
) -> tuple[NotificationDelivery, datetime]:
    await _subscribe(db, member)
    notification = await _write(db, member, org, NotificationEventType.RUN_COMPLETED)
    [delivery] = (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_id == notification.id,
                    NotificationDelivery.channel == "push",
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    delivery.claimed_at = now
    delivery.attempts = 1
    await db.flush()
    return delivery, now


class TestTheSweepSettlesAPush:
    @pytest.mark.parametrize(
        ("outcome", "result", "status"),
        [
            (PushOutcome(sent=1, gone=0, failed=1), "sent", DeliveryStatus.SENT),
            (PushOutcome(sent=0, gone=1, failed=0), "skipped", DeliveryStatus.SKIPPED),
            (PushOutcome(sent=0, gone=0, failed=2), "failed", DeliveryStatus.PENDING),
        ],
    )
    async def test_by_what_the_browsers_said(self, db, outcome, result, status):
        org, member = await _org_with_member(db)
        delivery, now = await _queued_push(db, member, org)
        send = AsyncMock(return_value=outcome)
        with patch("app.services.notification_delivery.PushService.send", new=send):
            assert (
                await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)
                == result
            )
        await db.refresh(delivery)
        assert delivery.status == status.value
        message = send.await_args.args[1]
        assert (message.body, message.url) == ("Your run finished", "/runs?run=r1")

    async def test_a_push_service_that_raises_is_retried_with_a_safe_reason(self, db):
        org, member = await _org_with_member(db)
        delivery, now = await _queued_push(db, member, org)
        with patch(
            "app.services.notification_delivery.PushService.send",
            new=AsyncMock(side_effect=OSError("https://fcm.googleapis.com/secret-token")),
        ):
            assert (
                await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)
                == "failed"
            )
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.PENDING.value
        assert "secret-token" not in (delivery.last_error or "")
        assert "push service" in (delivery.last_error or "")

    async def test_push_turned_off_after_it_was_queued_is_skipped(self, db):
        org, member = await _org_with_member(db)
        delivery, now = await _queued_push(db, member, org)
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=member.id,
                event_type=NotificationEventType.RUN_COMPLETED.value,
                channel="push",
                enabled=False,
            )
        )
        await db.flush()
        send = AsyncMock()
        with patch("app.services.notification_delivery.PushService.send", new=send):
            assert (
                await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)
                == "skipped"
            )
        send.assert_not_called()


class TestTheWritesThatAreSql:
    async def test_the_first_signing_key_stays_and_a_second_is_refused(self, db):
        first = await deployment_repo.claim_vapid_key(
            db, private_key="sealed-1", public_key="pub-1", key_version=1
        )
        second = await deployment_repo.claim_vapid_key(
            db, private_key="sealed-2", public_key="pub-2", key_version=1
        )
        assert (first.vapid_public_key, second.vapid_public_key) == ("pub-1", "pub-1")
        assert second.vapid_private_key == "sealed-1"

    async def test_a_browser_follows_whoever_subscribes_it_and_is_forgotten_for_them(self, db):
        endpoint = ENDPOINT + "shared"
        alice, bob = await _user(db), await _user(db)
        for user in (alice, bob):
            await push_repo.upsert(
                db, user_id=user.id, endpoint=endpoint, p256dh="BPk", auth="c2Vj", user_agent=None
            )
        rows = (await db.execute(select(PushSubscription))).scalars().all()
        assert [(row.user_id, row.endpoint) for row in rows] == [(bob.id, endpoint)]
        assert await push_repo.subscribed(db, [alice.id, bob.id]) == {bob.id}
        assert not await push_repo.delete_for_user(db, user_id=alice.id, endpoint=endpoint)
        assert await push_repo.delete_for_user(db, user_id=bob.id, endpoint=endpoint)
        assert await push_repo.subscribed(db, []) == set()

    async def test_an_iphone_follows_whoever_registers_it_and_is_forgotten_for_them(self, db):
        token = "cd" * 32
        alice, bob = await _user(db), await _user(db)
        for user in (alice, bob):
            await device_repo.upsert(db, user_id=user.id, token=token)
        rows = (await db.execute(select(ApnsDevice))).scalars().all()
        assert [(row.user_id, row.token) for row in rows] == [(bob.id, token)]
        assert await device_repo.subscribed(db, [alice.id, bob.id]) == {bob.id}
        assert not await device_repo.delete_for_user(db, user_id=alice.id, token=token)
        assert await device_repo.delete_for_user(db, user_id=bob.id, token=token)


class TestAnIphoneIsPushedTo:
    async def test_only_once_the_organization_has_set_its_apns_key(self, db):
        org, member = await _org_with_member(db)
        await device_repo.upsert(db, user_id=member.id, token="ef" * 32)
        notification = await _write(
            db, member, org, NotificationEventType.SECURITY_EVENT, use_savepoint=True
        )
        assert "push" not in await _channels(db, notification.id)
        await deployment_repo.upsert(
            db,
            update_data={
                "apns_private_key": "sealed",
                "apns_key_version": 1,
                "apns_key_id": "KEY1234567",
                "apns_team_id": "TEAM123456",
                "apns_topic": "com.acme.app",
                "apns_sandbox": False,
            },
        )
        notification = await _write(
            db, member, org, NotificationEventType.SECURITY_EVENT, use_savepoint=True
        )
        assert "push" in await _channels(db, notification.id)


@pytest.mark.parametrize("state", ["active", "revoked", "expired", "wrong-owner"])
async def test_linked_push_stops_with_its_own_session(db, state: str) -> None:
    from datetime import timedelta

    from app.repositories import session_repo

    user = await _user(db)
    owner = await _user(db) if state == "wrong-owner" else user
    session = await session_repo.create(
        db,
        user_id=owner.id,
        refresh_token_hash=uuid.uuid4().hex,
        expires_at=datetime.now(UTC) + timedelta(days=-1 if state == "expired" else 1),
    )
    if state == "revoked":
        session.is_active = False
        await db.flush()
    await push_repo.upsert(
        db,
        user_id=user.id,
        endpoint=ENDPOINT + uuid.uuid4().hex,
        p256dh="key",
        auth="auth",
        user_agent=None,
        session_id=session.id,
    )
    await device_repo.upsert(db, user_id=user.id, token=uuid.uuid4().hex * 2, session_id=session.id)
    expected = {user.id} if state == "active" else set()
    assert await push_repo.subscribed(db, [user.id]) == expected
    assert await device_repo.subscribed(db, [user.id]) == expected
    assert bool(await push_repo.list_for_user(db, user.id)) is (state == "active")
    assert bool(await device_repo.list_for_user(db, user.id)) is (state == "active")
