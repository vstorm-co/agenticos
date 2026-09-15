"""The delivery sweep's claim, send-time recheck and reap, against a real
database (#1598, phase 4 of `docs/design/notification-center-plan.md`).

Decision 3's whole guarantee rests on real SQL a mock cannot exercise: `FOR
UPDATE SKIP LOCKED` actually taking disjoint rows under two concurrent claims,
a settling `UPDATE` conditioned on `claimed_at` actually matching nothing once
a lease has moved on, and the window-function count on the failed-deliveries
view actually agreeing with the rows beside it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.notification_preference import NotificationChannelPreference
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.email.providers.base import SendResult
from app.services.email.service import EmailKey
from app.services.notification_delivery import NotificationDeliveryService

pytestmark = pytest.mark.anyio

MODULE = "app.services.notification_delivery"


async def _user(db, *, is_app_admin: bool = False, is_active: bool = True, **overrides) -> User:
    fields = {
        "id": uuid.uuid4(),
        "email": f"{uuid.uuid4().hex}@example.com",
        "hashed_password": "x",
        "is_active": is_active,
        "is_app_admin": is_app_admin,
    }
    fields.update(overrides)
    user = User(**fields)
    db.add(user)
    await db.flush()
    return user


async def _org(db, owner: User) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=owner.id, role="owner")
    )
    await db.flush()
    return org


async def _member(db, org: Organization, *, role: str) -> User:
    user = await _user(db)
    db.add(OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role=role))
    await db.flush()
    return user


async def _delivery(
    db,
    *,
    recipient: User,
    event_type: NotificationEventType = NotificationEventType.BUDGET_EXCEEDED,
    organization_id: uuid.UUID | None = None,
    render_context: dict | None = None,
    context_url: str | None = None,
    occurrence_id: str | None = None,
    status: str = DeliveryStatus.PENDING.value,
    attempts: int = 0,
    claimed_at: datetime | None = None,
    claimed_until: datetime | None = None,
) -> NotificationDelivery:
    notification = Notification(
        id=uuid.uuid4(),
        organization_id=organization_id,
        recipient_user_id=recipient.id,
        event_type=event_type.value,
        occurrence_id=occurrence_id or str(uuid.uuid4()),
        summary="A thing happened",
        context_url=context_url,
        render_context=render_context or {},
        in_app_visible=True,
    )
    db.add(notification)
    await db.flush()
    delivery = NotificationDelivery(
        id=uuid.uuid4(),
        notification_id=notification.id,
        channel="email",
        status=status,
        attempts=attempts,
        claimed_at=claimed_at,
        claimed_until=claimed_until,
    )
    db.add(delivery)
    await db.flush()
    return delivery


def _sent(message_id: str = "abc") -> MagicMock:
    """`get_email_service()` is a plain sync function - the mock replacing it
    must be too, or calling it returns a coroutine instead of the service."""
    service = AsyncMock()
    service.send = AsyncMock(return_value=SendResult(provider_message_id=message_id, accepted=True))
    return MagicMock(return_value=service)


def _rejected(error: str = "bounced") -> MagicMock:
    service = AsyncMock()
    service.send = AsyncMock(
        return_value=SendResult(provider_message_id="x", accepted=False, error=error)
    )
    return MagicMock(return_value=service)


class TestClaimAndAdvance:
    async def test_claiming_stamps_the_lease_and_increments_attempts(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        delivery = await _delivery(db, recipient=recipient, organization_id=org.id)
        now = datetime.now(UTC)

        claimed = await NotificationDeliveryService(db).claim_and_advance(now=now)

        assert [d.id for d in claimed] == [delivery.id]
        assert delivery.claimed_at == now
        assert delivery.claimed_until == now + timedelta(minutes=2)
        assert delivery.attempts == 1

    async def test_a_row_still_inside_its_lease_is_not_reclaimed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        await _delivery(
            db,
            recipient=recipient,
            organization_id=org.id,
            claimed_at=now,
            claimed_until=now + timedelta(minutes=2),
            attempts=1,
        )

        claimed = await NotificationDeliveryService(db).claim_and_advance(now=now)

        assert claimed == []

    async def test_a_row_past_its_lease_is_reclaimed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        past = datetime.now(UTC) - timedelta(hours=1)
        delivery = await _delivery(
            db,
            recipient=recipient,
            organization_id=org.id,
            claimed_at=past,
            claimed_until=past,
            attempts=1,
        )

        claimed = await NotificationDeliveryService(db).claim_and_advance(now=datetime.now(UTC))

        assert [d.id for d in claimed] == [delivery.id]
        assert delivery.attempts == 2

    async def test_an_exhausted_row_is_not_claimed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        await _delivery(db, recipient=recipient, organization_id=org.id, attempts=5)

        claimed = await NotificationDeliveryService(db).claim_and_advance(now=datetime.now(UTC))

        assert claimed == []

    async def test_a_sent_or_failed_row_is_never_claimed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        await _delivery(
            db, recipient=recipient, organization_id=org.id, status=DeliveryStatus.SENT.value
        )
        await _delivery(
            db, recipient=recipient, organization_id=org.id, status=DeliveryStatus.FAILED.value
        )

        claimed = await NotificationDeliveryService(db).claim_and_advance(now=datetime.now(UTC))

        assert claimed == []

    async def test_two_concurrent_sweeps_take_disjoint_rows(self, db, engine):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        await _delivery(db, recipient=recipient, organization_id=org.id)
        await db.commit()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as first:
            first_claim = await NotificationDeliveryService(first).claim_and_advance(
                now=datetime.now(UTC)
            )
            assert len(first_claim) == 1

            async with factory() as second:
                second_claim = await NotificationDeliveryService(second).claim_and_advance(
                    now=datetime.now(UTC)
                )
            assert second_claim == []


class TestReapExhausted:
    async def test_an_exhausted_unclaimed_lease_is_settled_failed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        past = datetime.now(UTC) - timedelta(hours=1)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, attempts=5, claimed_until=past
        )

        reaped = await NotificationDeliveryService(db).reap_exhausted(now=datetime.now(UTC))

        assert reaped == 1
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED.value
        assert delivery.last_error == "exhausted without a recorded outcome"

    async def test_a_row_not_yet_past_its_lease_is_left_alone(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        future = datetime.now(UTC) + timedelta(minutes=5)
        await _delivery(
            db, recipient=recipient, organization_id=org.id, attempts=5, claimed_until=future
        )

        reaped = await NotificationDeliveryService(db).reap_exhausted(now=datetime.now(UTC))

        assert reaped == 0

    async def test_a_row_with_attempts_remaining_is_left_alone(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        past = datetime.now(UTC) - timedelta(hours=1)
        await _delivery(
            db, recipient=recipient, organization_id=org.id, attempts=2, claimed_until=past
        )

        reaped = await NotificationDeliveryService(db).reap_exhausted(now=datetime.now(UTC))

        assert reaped == 0


class TestSendAndSettleLostClaim:
    async def test_a_stale_claim_token_settles_nothing(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        outcome = await NotificationDeliveryService(db).send_and_settle(
            delivery.id, claimed_at=now - timedelta(minutes=5)
        )

        assert outcome == "lost_claim"

    async def test_a_missing_delivery_settles_nothing(self, db):
        outcome = await NotificationDeliveryService(db).send_and_settle(
            uuid.uuid4(), claimed_at=datetime.now(UTC)
        )
        assert outcome == "lost_claim"


class TestSendAndSettleReachability:
    async def test_an_inactive_recipient_is_skipped(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        recipient.is_active = False
        await db.flush()
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)

        assert outcome == "skipped"
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.SKIPPED.value

    async def test_a_recipient_who_left_the_organization_is_skipped(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        membership = await db.scalar(
            select(OrganizationMember).where(OrganizationMember.user_id == recipient.id)
        )
        await db.delete(membership)
        await db.flush()
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)

        assert outcome == "skipped"

    async def test_a_deployment_wide_event_needs_current_app_admin_status(self, db):
        recipient = await _user(db, is_app_admin=False)
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=recipient,
            organization_id=None,
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            claimed_at=now,
            attempts=1,
        )

        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)

        assert outcome == "skipped"

    async def test_a_deployment_wide_event_reaches_a_current_app_admin(self, db):
        recipient = await _user(db, is_app_admin=True)
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=recipient,
            organization_id=None,
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            render_context={"agent_name": "x"},
            claimed_at=now,
            attempts=1,
        )

        with patch(f"{MODULE}.get_email_service", new=_sent()):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"


class TestSendAndSettlePreference:
    async def test_an_ordinary_event_is_skipped_when_email_is_off(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        recipient.notify_budget_alerts = False
        await db.flush()
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)

        assert outcome == "skipped"

    async def test_a_mandatory_event_ignores_the_preference_and_reaches_the_render_step(self, db):
        """The proof the bypass took effect: the preference is off, but the
        send still happens - had the preference actually been consulted and
        honoured, this would have short-circuited to `skipped` before ever
        reaching render or send."""
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        db.add(
            NotificationChannelPreference(
                id=uuid.uuid4(),
                user_id=admin.id,
                event_type=NotificationEventType.SECURITY_EVENT.value,
                channel="email",
                enabled=False,
            )
        )
        await db.flush()
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=admin,
            organization_id=org.id,
            event_type=NotificationEventType.SECURITY_EVENT,
            claimed_at=now,
            attempts=5,
        )

        with patch(f"{MODULE}.get_email_service", new=_sent()):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"


class TestRenderDispatch:
    async def test_an_event_type_with_no_bespoke_template_uses_the_generic_fallback(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=admin,
            organization_id=org.id,
            event_type=NotificationEventType.SECURITY_EVENT,
            context_url="https://app.example.com/audit",
            claimed_at=now,
            attempts=1,
        )

        service = AsyncMock()
        service.send = AsyncMock(return_value=SendResult(provider_message_id="x", accepted=True))
        with patch(f"{MODULE}.get_email_service", return_value=service):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"
        assert service.send.call_args.kwargs["key"] is EmailKey.NOTIFICATION
        context = service.send.call_args.kwargs["context"]
        assert context["context_url"] == "https://app.example.com/audit"
        assert context["summary"] == "A thing happened"
        assert context["app_name"]

    async def test_budget_exceeded_renders_its_own_key_unchanged(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=recipient,
            organization_id=org.id,
            event_type=NotificationEventType.BUDGET_EXCEEDED,
            render_context={"agent_name": "Support", "reason": "cap"},
            claimed_at=now,
            attempts=1,
        )

        service = AsyncMock()
        service.send = AsyncMock(return_value=SendResult(provider_message_id="x", accepted=True))
        with patch(f"{MODULE}.get_email_service", return_value=service):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"
        assert service.send.call_args.kwargs["key"] is EmailKey.BUDGET_EXCEEDED
        assert service.send.call_args.kwargs["to"] == recipient.email
        assert service.send.call_args.kwargs["context"] == {
            "agent_name": "Support",
            "reason": "cap",
        }

    async def test_a_usage_report_and_an_agent_usage_report_share_one_key(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        admin = await _member(db, org, role="admin")
        now = datetime.now(UTC)
        for event_type in (
            NotificationEventType.USAGE_REPORT,
            NotificationEventType.AGENT_USAGE_REPORT,
        ):
            delivery = await _delivery(
                db,
                recipient=admin,
                organization_id=org.id,
                event_type=event_type,
                claimed_at=now,
                attempts=1,
            )
            service = AsyncMock()
            service.send = AsyncMock(
                return_value=SendResult(provider_message_id="x", accepted=True)
            )
            with patch(f"{MODULE}.get_email_service", return_value=service):
                outcome = await NotificationDeliveryService(db).send_and_settle(
                    delivery.id, claimed_at=now
                )
            assert outcome == "sent"
            assert service.send.call_args.kwargs["key"] is EmailKey.USAGE_REPORT

    async def test_a_decider_gets_the_full_context_a_non_decider_loses_the_link(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        decider = await _member(db, org, role="operator")  # holds approvals:decide
        non_decider = await _member(db, org, role="member")
        now = datetime.now(UTC)

        for recipient, expected_key, keeps_link in (
            (decider, EmailKey.APPROVAL_REQUESTED, True),
            (non_decider, EmailKey.APPROVAL_PENDING, False),
        ):
            delivery = await _delivery(
                db,
                recipient=recipient,
                organization_id=org.id,
                event_type=NotificationEventType.APPROVAL_REQUESTED,
                render_context={"tools": "x", "approvals_url": "https://app.example.com/runs"},
                claimed_at=now,
                attempts=1,
            )
            service = AsyncMock()
            service.send = AsyncMock(
                return_value=SendResult(provider_message_id="x", accepted=True)
            )
            with patch(f"{MODULE}.get_email_service", return_value=service):
                outcome = await NotificationDeliveryService(db).send_and_settle(
                    delivery.id, claimed_at=now
                )
            assert outcome == "sent"
            assert service.send.call_args.kwargs["key"] is expected_key
            context = service.send.call_args.kwargs["context"]
            assert ("approvals_url" in context) is keeps_link

    async def test_an_app_admin_always_counts_as_a_decider(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        app_admin_member = await _member(db, org, role="member")
        app_admin_member.is_app_admin = True
        await db.flush()
        now = datetime.now(UTC)
        delivery = await _delivery(
            db,
            recipient=app_admin_member,
            organization_id=org.id,
            event_type=NotificationEventType.APPROVAL_REQUESTED,
            render_context={"tools": "x", "approvals_url": "https://app.example.com/runs"},
            claimed_at=now,
            attempts=1,
        )
        service = AsyncMock()
        service.send = AsyncMock(return_value=SendResult(provider_message_id="x", accepted=True))
        with patch(f"{MODULE}.get_email_service", return_value=service):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"
        assert service.send.call_args.kwargs["key"] is EmailKey.APPROVAL_REQUESTED


class TestOutcomesAndRetry:
    async def test_a_dangling_notification_fails_the_row(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )
        notification = await db.get(Notification, delivery.notification_id)
        assert notification is not None
        await db.delete(notification)
        await db.flush()

        outcome = await NotificationDeliveryService(db).send_and_settle(delivery.id, claimed_at=now)

        assert outcome == "failed"

    async def test_a_provider_rejection_with_attempts_remaining_retries(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        with patch(f"{MODULE}.get_email_service", new=_rejected("bounced")):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "failed"
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.PENDING.value
        assert delivery.last_error == "bounced"

    async def test_a_provider_rejection_with_no_attempts_left_is_exhausted(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=5
        )

        with patch(f"{MODULE}.get_email_service", new=_rejected("bounced")):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "failed"
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.FAILED.value

    async def test_a_provider_exception_is_recorded_and_retried(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )
        service = AsyncMock()
        service.send = AsyncMock(side_effect=RuntimeError("smtp down"))
        with patch(f"{MODULE}.get_email_service", return_value=service):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "failed"
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.PENDING.value
        assert "smtp down" in delivery.last_error

    async def test_a_hung_send_is_cancelled_at_the_timeout(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        async def _hangs(**_kwargs):
            await asyncio.sleep(10)
            return SendResult(provider_message_id="x", accepted=True)  # pragma: no cover

        service = AsyncMock()
        service.send = _hangs
        with (
            patch(f"{MODULE}.get_email_service", return_value=service),
            patch(f"{MODULE}.SEND_TIMEOUT_SECONDS", 0.01),
        ):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "failed"
        await db.refresh(delivery)
        assert delivery.last_error == "send timed out"

    async def test_a_successful_send_is_recorded_sent(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        now = datetime.now(UTC)
        delivery = await _delivery(
            db, recipient=recipient, organization_id=org.id, claimed_at=now, attempts=1
        )

        with patch(f"{MODULE}.get_email_service", new=_sent()):
            outcome = await NotificationDeliveryService(db).send_and_settle(
                delivery.id, claimed_at=now
            )

        assert outcome == "sent"
        await db.refresh(delivery)
        assert delivery.status == DeliveryStatus.SENT.value
        assert delivery.last_error is None


class TestListFailed:
    async def test_only_terminally_failed_rows_are_listed(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        await _delivery(
            db, recipient=recipient, organization_id=org.id, status=DeliveryStatus.SENT.value
        )
        failed = await _delivery(
            db, recipient=recipient, organization_id=org.id, status=DeliveryStatus.FAILED.value
        )

        rows, total = await NotificationDeliveryService(db).list_failed(skip=0, limit=50)

        assert total == 1
        assert [delivery.id for delivery, _notification in rows] == [failed.id]

    async def test_pagination_and_total_agree(self, db):
        owner = await _user(db)
        org = await _org(db, owner)
        recipient = await _member(db, org, role="member")
        for _ in range(3):
            await _delivery(
                db, recipient=recipient, organization_id=org.id, status=DeliveryStatus.FAILED.value
            )

        first_page, total = await NotificationDeliveryService(db).list_failed(skip=0, limit=2)
        second_page, _ = await NotificationDeliveryService(db).list_failed(skip=2, limit=2)

        assert total == 3
        assert len(first_page) == 2
        assert len(second_page) == 1
