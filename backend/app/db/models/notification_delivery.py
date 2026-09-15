"""A claimed, retried send on one channel, for one notification (#1598).

Every email this feature concerns itself with - including the four existing
agent-lifecycle ones - goes through a row here rather than a fire-and-forget
`spawn`, so a transient provider outage is a retry, not a silently dropped
notice. Claiming a row and sending on it are deliberately two transactions,
modelled on `agent_trigger_repo.claim_due`'s `FOR UPDATE SKIP LOCKED` shape:
`docs/design/notification-center-plan.md`, Decision 3, has the full reasoning
for why `attempts` increments at claim time rather than on a recorded outcome,
and why a settling `UPDATE` is conditioned on still holding the claim it was
issued.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DeliveryStatus(enum.StrEnum):
    """A delivery row's lifecycle. `PENDING` is the only retryable state.

    An earlier design let a claim query match `PENDING` or `FAILED`, which made
    `FAILED` mean two different things - "will retry" and "gave up",
    indistinguishable to the admin failed-deliveries view. The rule is one, not
    a new column: a failed send with attempts remaining writes the row back to
    `PENDING`; only a send with none remaining, or the sweep's own reaper step
    for a row exhausted with no recorded outcome, writes `FAILED`. `FAILED` then
    means exactly one thing everywhere it is read.
    """

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class NotificationDelivery(Base, TimestampMixin):
    """One channel's send for one :class:`app.db.models.notification.Notification`."""

    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # CASCADE: retention's hard delete of a `notifications` row (Decision 8)
    # must not be blocked by a delivery row that still references it, and a
    # restrictive default FK would do exactly that.
    notification_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Only `email` ships today; `NotificationChannel` also carries `in_app`,
    # which never gets a delivery row - the `Notification` row itself is the
    # in-app delivery.
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The lease: stamped by the claim, alongside incrementing `attempts`, in the
    # same committed transaction. `claimed_until` is when another worker may
    # reclaim the row; it is not, by itself, a bound on how long the original
    # worker's own `send()` call may run - the sweep wraps that call in its own
    # timeout, well under this lease (Decision 3).
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("channel = 'email'", name="ck_notification_deliveries_channel"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped')",
            name="ck_notification_deliveries_status",
        ),
        # The sweep's claim query: pending rows whose lease has lapsed or was
        # never taken. Partial, since `sent`/`failed`/`skipped` rows - the
        # overwhelming majority once a deployment has run for a while - are
        # never claimed again.
        Index(
            "notification_deliveries_claim_idx",
            "status",
            "claimed_until",
            postgresql_where=sa_text("status = 'pending'"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery(id={self.id}, notification_id={self.notification_id}, "
            f"channel={self.channel}, status={self.status})>"
        )
