"""Something a person asked the platform to keep an eye on in one of their connections (#2301).

A watch is the proactive look pointed at a service: read the person's own MCP
connection on a cadence they chose, and say what is new - an invoice past due,
pull requests waiting on their review. Only that connection's read-only tools
are in reach, and what it finds is written for the person alone, as a
`Suggestion` of kind `finding` keyed so the same thing is never reported twice.

A watch is a read-only ongoing responsibility of a selected published agent.
It normally stays quiet without new findings, or sends an explicitly requested
report after every successful check. Its cadence is an interval, never more
often than its organization allows (`Organization.proactive_watch_min_minutes`).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MIN_WATCH_MINUTES = 15
"""The most often any watch is read: a model call per look, booked to the person's limit."""


class WatchAttemptStatus(enum.StrEnum):
    COMPLETED = "completed"
    SOURCE_UNAVAILABLE = "source_unavailable"
    ACCESS_REVOKED = "access_revoked"
    NOT_COMPLETED = "not_completed"
    NEEDS_AGENT = "needs_agent"
    BUDGET_PAUSED = "budget_paused"
    DELIVERY_UNAVAILABLE = "delivery_unavailable"


class Watch(Base, TimestampMixin):
    """One thing one person watches in one of their own connections."""

    __tablename__ = "watches"
    __table_args__ = (
        CheckConstraint(
            "max_failures IS NULL OR max_failures BETWEEN 1 AND 20", name="ck_routine_max_failures"
        ),
        CheckConstraint("consecutive_failures BETWEEN 0 AND 20", name="ck_routine_failure_count"),
        Index(
            "ix_watches_pending_end",
            "ends_at",
            "id",
            postgresql_where=text(
                "ends_at IS NOT NULL AND (is_active OR end_settled_at IS DISTINCT FROM ends_at)"
            ),
        ),
        CheckConstraint("report_mode IN ('changes', 'every_check')", name="ck_watch_report_mode"),
        CheckConstraint(
            "pinned_version_id IS NULL OR environment_id IS NULL", name="ck_watch_version_selection"
        ),
        CheckConstraint(
            "agent_id IS NULL OR approved_sources IS NOT NULL", name="ck_watch_approved_sources"
        ),
        CheckConstraint(
            f"interval_minutes >= {MIN_WATCH_MINUTES}", name="ck_watch_interval_minutes"
        ),
        CheckConstraint(
            "(last_attempt_at IS NULL AND last_attempt_status IS NULL) OR "
            "(last_attempt_at IS NOT NULL AND last_attempt_status IS NOT NULL AND "
            "last_attempt_status IN ('completed', 'source_unavailable', 'access_revoked', 'not_completed', 'needs_agent', 'budget_paused', 'delivery_unavailable'))",
            name="ck_watch_attempt_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The person's own connection; a disconnected account takes its watches with it.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    pinned_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_environments.id", ondelete="SET NULL"), nullable=True
    )
    approved_sources: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The deadline already settled, so moving the end rearms cleanup.
    end_settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_channels: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    last_reported_activation: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    report_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="changes", server_default="changes"
    )
    # The catalog preset it was made from, or null for one the person described.
    preset_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    """What to look for, in the person's words or the preset's."""
    # What the person said they want less of, one line each - read on every look.
    exclusions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Whether a finding the model judges urgent is sent at once rather than
    # waiting for the morning briefing.
    urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_failures: Mapped[int | None] = mapped_column(
        Integer().evaluates_none(), nullable=True, default=3, server_default=text("3")
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    health_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_status: Mapped[WatchAttemptStatus | None] = mapped_column(
        String(32), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Watch(id={self.id}, user={self.user_id}, every={self.interval_minutes}m)>"
