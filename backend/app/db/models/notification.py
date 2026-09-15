"""A per-recipient row a person can read and mark read (#1598).

Every event this feature covers - budget, approvals, run completion, ingestion,
security, configuration changes, reports, an app admin's own announcement -
resolves to one row here per person it is addressed to. The row existing *is*
the in-app delivery; nothing further has to succeed for it to show up in an
inbox. A side channel (email today) is a separate, retried
:class:`app.db.models.notification_delivery.NotificationDelivery` row, because
only that part can fail independently of the write that created this one - see
`docs/design/notification-center-plan.md`, Decisions 2 and 3.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class NotificationEventType(enum.StrEnum):
    """Every event this feature covers, code-defined rather than admin-configured.

    The mapping from a value here to its producer, default audience, content
    gate and mandatory-ness is a table in code
    (:mod:`app.services.notification_catalog`, added alongside the write path),
    not a form an admin fills in. This enum is only the vocabulary the schema's
    CHECK constraints hold every row to.
    """

    BUDGET_EXCEEDED = "budget_exceeded"
    APPROVAL_REQUESTED = "approval_requested"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    INGESTION_COMPLETED = "ingestion_completed"
    INGESTION_FAILED = "ingestion_failed"
    USAGE_REPORT = "usage_report"
    AGENT_USAGE_REPORT = "agent_usage_report"
    SECURITY_EVENT = "security_event"
    CONFIGURATION_CHANGED = "configuration_changed"
    ANNOUNCEMENT = "announcement"


class NotificationChannel(enum.StrEnum):
    """A channel a notification reaches a recipient through.

    `notification_preferences.channel` (Decision 4) holds both values, since a
    person can turn each off independently. `notification_deliveries.channel`
    (Decision 3) only ever holds `EMAIL` - in-app has no delivery row, because
    the :class:`Notification` row itself is the in-app delivery.
    """

    IN_APP = "in_app"
    EMAIL = "email"


class Notification(Base, TimestampMixin):
    """One event, addressed to one recipient."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Null for a deployment-wide event with no tenant to scope it to
    # (`configuration_changed`, and any `security_event` row addressed to a
    # deployment app admin rather than an organization's own admins) - see
    # Decision 2. `GET /notifications` matches a row whose organization_id is
    # null regardless of the caller's active organization, the same way an app
    # admin's own authority is not organization-scoped.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # The dedup key from Decision 1's catalog table - a run id, an
    # `(document id, ingestion_attempt)` pair joined with `:`, an
    # `AppAdminAuditLog` id, and so on. Enforced unique per
    # `(recipient_user_id, event_type)` below, so a retried trigger for the same
    # fact is a no-op insert, not a second row.
    occurrence_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Pre-rendered at write time by the code that already knows what is and is
    # not safe to show - never a raw comment, file name or secret value passed
    # through unchecked.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    context_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The typed template variables the row's `EmailKey` needs to re-render at
    # send time, frozen at write time - not re-derived, so a delayed retry
    # describes the same numbers it was generated with rather than whatever is
    # true by the time it finally sends (Decision 2/3).
    render_context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # This recipient's in-app preference for this (event_type, IN_APP) pair,
    # resolved once at write time (Decision 4). An email-only row still gets a
    # notifications row - it is also the dedup anchor regardless of which
    # channels end up active - it is simply never returned by the inbox, the
    # unread count or mark-all-read, all three of which filter on this column.
    in_app_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The announcement this row fans out from, when event_type=announcement.
    # SET NULL rather than CASCADE: Decision 8 deliberately excludes
    # `announcements` from the retention sweep specifically so "what did an app
    # admin send" outlives the individual deliveries it produced, and a
    # dangling reference here would not make a written, frozen `summary`
    # unreadable.
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("announcements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
            "'ingestion_completed', 'ingestion_failed', 'usage_report', "
            "'agent_usage_report', 'security_event', 'configuration_changed', "
            "'announcement')",
            name="ck_notifications_event_type",
        ),
        # The dedup guarantee (Decision 2): a retried trigger for the same fact,
        # addressed to the same person, is a no-op insert rather than a second
        # row - enforced by Postgres inside the same transaction, not a
        # separate, expiring cache.
        Index(
            "notifications_recipient_event_occurrence_idx",
            "recipient_user_id",
            "event_type",
            "occurrence_id",
            unique=True,
        ),
        # The paginated inbox: `WHERE recipient_user_id = : AND in_app_visible
        # ORDER BY created_at DESC, id DESC` - `id` breaks a tie `created_at`
        # alone cannot, since one transaction (a report flow writing several
        # recipients' rows together) can give more than one row the identical
        # timestamp. The partial `WHERE` keeps an email-only row
        # (in_app_visible=false) out of it entirely, since none of the three
        # inbox read paths ever return one.
        Index(
            "notifications_inbox_idx",
            "recipient_user_id",
            sa_text("created_at DESC"),
            sa_text("id DESC"),
            postgresql_where=sa_text("in_app_visible"),
        ),
        # The unread-count badge: `WHERE recipient_user_id = : AND
        # in_app_visible AND read_at IS NULL`. The same gate-aware predicate the
        # inbox and mark-all-read apply (Decision 7) - none of the three may
        # take a cheaper, gate-blind filter.
        Index(
            "notifications_unread_idx",
            "recipient_user_id",
            postgresql_where=sa_text("in_app_visible AND read_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification(id={self.id}, event_type={self.event_type}, "
            f"recipient={self.recipient_user_id})>"
        )


# How long a *read* notification is kept, and the outer bound past which any
# row is dropped regardless of read state (#1598, Decision 8) - ahead of
# #1420, which does not exist yet; this is a bounded default rather than an
# integration with a per-organization mechanism this plan cannot predict.
# `announcements` is deliberately untouched by the sweep these constants
# bound: deleting the per-recipient rows a broadcast fanned out to does not
# delete the announcement itself, which is what `record_audit`'s
# `announcement_id` (Decision 5) keeps pointing at.
NOTIFICATION_READ_RETENTION_DAYS = 90
NOTIFICATION_OUTER_RETENTION_DAYS = 365
