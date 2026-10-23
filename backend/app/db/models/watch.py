"""Something a person asked the platform to keep an eye on in one of their connections (#2301).

A watch is the proactive look pointed at a service: read the person's own MCP
connection on a cadence they chose, and say what is new - an invoice past due,
pull requests waiting on their review. Only that connection's read-only tools
are in reach, and what it finds is written for the person alone, as a
`Suggestion` of kind `finding` keyed so the same thing is never reported twice.

It is not a routine. A routine is an agent run whose answer is a message; a
watch's answer is a handful of findings or nothing, and nothing is the usual
answer. Its cadence is an interval, never more often than its organization
allows (`Organization.proactive_watch_min_minutes`).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MIN_WATCH_MINUTES = 15
"""The most often any watch is read: a model call per look, booked to the person's limit."""


class Watch(Base, TimestampMixin):
    """One thing one person watches in one of their own connections."""

    __tablename__ = "watches"
    __table_args__ = (
        CheckConstraint(
            f"interval_minutes >= {MIN_WATCH_MINUTES}", name="ck_watch_interval_minutes"
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
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Watch(id={self.id}, user={self.user_id}, every={self.interval_minutes}m)>"
