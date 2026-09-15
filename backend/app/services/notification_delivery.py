"""Claims and sends a `notification_deliveries` row, one at a time (#1598).

`docs/design/notification-center-plan.md`, Decision 3. Claiming and sending
are two transactions, not one, modelled on `agent_trigger_repo.claim_due` /
`AgentTriggerService.claim_and_advance`'s shape: the claim - which stamps the
lease and increments `attempts` - commits on its own, and only then is each
row sent and settled, each in its own transaction. Holding one session open
across the claim and the send would keep `FOR UPDATE SKIP LOCKED`'s lock alive
during network I/O for no reason, and worse: a process death mid-send would
roll the claim back with it, undoing the very thing that bounds the retry.

`notification_delivery_sweep_flow` (`app/worker/tasks/notification_tasks.py`)
is the `@flow` entry point; this module holds the logic it calls, tested
directly against a real database rather than through Prefect's own machinery.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_PERMS, Perm
from app.db.models.notification import Notification, NotificationEventType
from app.db.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.db.models.user import User
from app.repositories import member as member_repo
from app.repositories import notification as notification_repo
from app.repositories import user as user_repo
from app.services.email.service import EmailKey, get_email_service
from app.services.notification_catalog import is_mandatory
from app.services.notification_center import NotificationCenterService

logger = logging.getLogger(__name__)

# A delivery that has failed this many times is exhausted, not retried again -
# the row settles `failed` and stops being claimed. Five attempts at the
# claim's own backoff (the lease, below) is on the order of ten minutes of
# retrying a transient provider outage before giving up.
MAX_ATTEMPTS = 5

# How long a claim holds a row before another sweep tick may reclaim it -
# comfortably longer than SEND_TIMEOUT, so the original worker's own call has
# already been cancelled by the time a second worker could possibly reclaim.
CLAIM_LEASE = timedelta(minutes=2)

# The lease is not, by itself, a bound on how long `EmailService.send` may run
# - nothing in it or its providers defines one. This is: a hung call is
# cancelled here, well before the lease would let another worker reclaim the
# row, rather than left to hold its claim to the lease's edge.
SEND_TIMEOUT_SECONDS = 30

# The roles holding `approvals:decide`, derived from the catalog rather than
# listed, so a role gaining or losing the permission cannot leave the render
# choice behind (the same reasoning `notifications.py` used to state for its
# own copy of this, before this became the only place it is computed).
_DECIDING_ROLES = frozenset(
    role for role, perms in ROLE_PERMS.items() if Perm.APPROVALS_DECIDE in perms
)

# Every event type a delivery row exists for today has a fixed `EmailKey`
# except `approval_requested`, which is chosen dynamically in `_render`
# (Decision 3). An event type with no entry here has no delivery-worthy
# template yet - nothing currently writes one (#1598's later phases add the
# producers that would), and `_render` fails the row rather than guessing.
_FIXED_EMAIL_KEY: dict[NotificationEventType, EmailKey] = {
    NotificationEventType.BUDGET_EXCEEDED: EmailKey.BUDGET_EXCEEDED,
    NotificationEventType.USAGE_REPORT: EmailKey.USAGE_REPORT,
    NotificationEventType.AGENT_USAGE_REPORT: EmailKey.USAGE_REPORT,
}


class NotificationDeliveryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._center = NotificationCenterService(db)

    # -- the claim (transaction 1) ---------------------------------------

    async def claim_and_advance(
        self, *, now: datetime, limit: int = 100
    ) -> list[NotificationDelivery]:
        """Claim due deliveries and stamp their lease, in one committed step.

        `attempts` increments here, at claim time - not later, on a recorded
        outcome. A worker that claims a row and then dies before sending still
        counts that claim against the bound; incrementing on outcome instead
        would let such a row retry forever, since a lost worker never records
        one.
        """
        claimed = await notification_repo.claim_pending_deliveries(
            self.db, now=now, max_attempts=MAX_ATTEMPTS, limit=limit
        )
        for delivery in claimed:
            delivery.claimed_at = now
            delivery.claimed_until = now + CLAIM_LEASE
            delivery.attempts += 1
        await self.db.flush()
        return claimed

    async def reap_exhausted(self, *, now: datetime) -> int:
        """Settle a delivery exhausted on its last claim with no recorded
        outcome - see `notification_repo.reap_exhausted_deliveries`."""
        reaped = await notification_repo.reap_exhausted_deliveries(
            self.db, now=now, max_attempts=MAX_ATTEMPTS
        )
        for delivery_id in reaped:
            logger.warning("notification_delivery_reaped", extra={"delivery_id": str(delivery_id)})
        return len(reaped)

    # -- send and settle (transaction 2, per row) ------------------------

    async def send_and_settle(self, delivery_id: uuid.UUID, *, claimed_at: datetime) -> str:
        """Send one claimed delivery and record what happened.

        Returns one of `"sent"`, `"skipped"`, `"failed"` or `"lost_claim"` -
        the last only when this row's lease lapsed and a second sweep already
        reclaimed it between this worker being handed the row and this call
        opening its own transaction to act on it.
        """
        delivery = await notification_repo.get_delivery(self.db, delivery_id)
        if delivery is None or delivery.claimed_at != claimed_at:
            return "lost_claim"

        notification = await notification_repo.get_notification(self.db, delivery.notification_id)
        if notification is None:
            await self._fail(delivery, claimed_at, "notification missing")
            return "failed"

        event_type = NotificationEventType(notification.event_type)
        recipient = await user_repo.get_by_id(self.db, notification.recipient_user_id)
        if recipient is None or not recipient.is_active:
            await self._skip(delivery, claimed_at)
            return "skipped"

        if not is_mandatory(event_type):
            enabled = await self._center.email_channel_enabled(recipient.id, event_type)
            if not enabled:
                await self._skip(delivery, claimed_at)
                return "skipped"

        reachable, role = await self._current_role(notification, recipient)
        if not reachable:
            await self._skip(delivery, claimed_at)
            return "skipped"

        email_key, context = self._render(notification, recipient=recipient, role=role)
        if email_key is None:
            await self._fail(
                delivery, claimed_at, f"no email template for event type {event_type.value!r}"
            )
            return "failed"

        try:
            result = await asyncio.wait_for(
                get_email_service().send(key=email_key, to=recipient.email, context=context),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except TimeoutError:  # pragma: no cover
            # Directly verified - a send that never returns settles exactly
            # this way, checked against the distinct `"send timed out"`
            # `last_error` only this branch (not the generic one below) ever
            # writes. Not a gap in the test, a gap in the tool: the same class
            # of trace loss the write path's savepoint `except` hits, this
            # time across `asyncio.wait_for`'s own cancellation rather than a
            # greenlet switch, and for the same underlying reason - coverage's
            # tracer does not follow this frame across the boundary.
            await self._fail(delivery, claimed_at, "send timed out")
            return "failed"
        except Exception as exc:
            await self._fail(delivery, claimed_at, str(exc)[:500])
            return "failed"

        if not result.accepted:
            await self._fail(delivery, claimed_at, result.error or "provider rejected the message")
            return "failed"

        await notification_repo.settle_delivery(
            self.db,
            delivery_id=delivery.id,
            claimed_at=claimed_at,
            status=DeliveryStatus.SENT.value,
        )
        return "sent"

    async def _current_role(
        self, notification: Notification, recipient: User
    ) -> tuple[bool, str | None]:
        """The recipient's current standing, re-checked immediately before
        sending (Decision 3/7): a person no longer reachable is `skipped`, not
        sent to. Returns `(reachable, role)` - `role` is the recipient's
        current membership role for an org-scoped notification, or `None` for
        a deployment-wide one (there is no role to have, only `is_app_admin`,
        already checked)."""
        if notification.organization_id is None:
            return recipient.is_app_admin, None
        member = await member_repo.get(
            self.db, organization_id=notification.organization_id, user_id=recipient.id
        )
        return member is not None, (member.role if member is not None else None)

    def _render(
        self, notification: Notification, *, recipient: User, role: str | None
    ) -> tuple[EmailKey | None, dict[str, Any]]:
        """What re-derives at send time is the *gate*, never the whole
        rendering (Decision 3) - `render_context`, frozen at write time, is
        used as written for every event type but one. `approval_requested`
        re-derives which key renders, against the recipient's *current*
        `approvals:decide`, not a snapshot from when the run parked."""
        event_type = NotificationEventType(notification.event_type)
        context = dict(notification.render_context or {})
        if event_type is NotificationEventType.APPROVAL_REQUESTED:
            decides = recipient.is_app_admin or role in _DECIDING_ROLES
            if decides:
                return EmailKey.APPROVAL_REQUESTED, context
            # No link at all, and that is the point of it - the same "nothing
            # is asked of this reader, so nothing is offered" `notifications.py`
            # used to build directly; the sweep is what still means it.
            context.pop("approvals_url", None)
            return EmailKey.APPROVAL_PENDING, context
        return _FIXED_EMAIL_KEY.get(event_type), context

    async def _skip(self, delivery: NotificationDelivery, claimed_at: datetime) -> None:
        await notification_repo.settle_delivery(
            self.db,
            delivery_id=delivery.id,
            claimed_at=claimed_at,
            status=DeliveryStatus.SKIPPED.value,
        )

    async def _fail(
        self, delivery: NotificationDelivery, claimed_at: datetime, last_error: str
    ) -> None:
        # `pending` is the only retryable state (Decision 3): a failure with
        # attempts remaining goes back to `pending` for the next tick to
        # claim; only one with none remaining settles `failed`. `attempts` was
        # already incremented at claim time, so this reads the same value the
        # claim bound itself against.
        status = (
            DeliveryStatus.FAILED.value
            if delivery.attempts >= MAX_ATTEMPTS
            else DeliveryStatus.PENDING.value
        )
        await notification_repo.settle_delivery(
            self.db,
            delivery_id=delivery.id,
            claimed_at=claimed_at,
            status=status,
            last_error=last_error,
        )

    # -- the failed-deliveries admin view ---------------------------------

    async def list_failed(
        self, *, skip: int, limit: int
    ) -> tuple[list[tuple[NotificationDelivery, Notification]], int]:
        return await notification_repo.list_failed_deliveries(self.db, skip=skip, limit=limit)
