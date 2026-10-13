"""Per-user, per-event, per-channel notification preferences (#1598).

Named `NotificationChannelPreference`, not `NotificationPreference` -
`app.db.models.user.NotificationPreference` already names the `Literal` for the
three legacy boolean columns (`notify_budget_alerts` and the like), which stay
exactly as they are and stay authoritative for the **email** channel of the
three agent-lifecycle events they already cover. This table covers every other
`(event_type, channel)` pair - the two vocabularies never overlap, so there is
exactly one authoritative lookup per pair rather than two that could disagree
(`docs/design/notification-center-plan.md`, Decision 4).
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class NotificationChannelPreference(Base, TimestampMixin):
    """Whether one user wants one event type on one channel."""

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
            "'ingestion_completed', 'ingestion_failed', 'usage_report', "
            "'agent_usage_report', 'security_event', 'configuration_changed', "
            "'announcement')",
            name="ck_notification_preferences_event_type",
        ),
        CheckConstraint(
            "channel IN ('in_app', 'email')", name="ck_notification_preferences_channel"
        ),
        # `PATCH` is an upsert against this constraint (`INSERT ... ON CONFLICT
        # ... DO UPDATE`), never a plain insert - without it, two concurrent
        # first-time requests for the same pair race an insert instead of an
        # update, and can leave two rows disagreeing on `enabled` for a lookup
        # this plan treats as authoritative.
        UniqueConstraint(
            "user_id",
            "event_type",
            "channel",
            name="uq_notification_preferences_user_event_channel",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationChannelPreference(user_id={self.user_id}, "
            f"event_type={self.event_type}, channel={self.channel}, enabled={self.enabled})>"
        )
