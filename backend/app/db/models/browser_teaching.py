"""Owner-bound structural browser recordings; no page content or input-value column exists."""

import uuid
from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BrowserTeachingSession(Base, TimestampMixin):
    """One person's demonstration in one held tab of one run.

    `call_id` and `tab_id` name the live browser view. They are references, not
    a CDP endpoint or a credential. `hold_id` is the human-control lease the
    session is bound to; a new hold gets a new id, and capture accepts events
    only while the row's hold id is the one the owner currently holds.
    """

    __tablename__ = "browser_teaching_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tab_id: Mapped[str] = mapped_column(String(200), nullable=False)
    hold_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sanitized_events: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    review: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    """Reviewed steps: a sequence, a reviewer's safe label and an optional parameter name."""
    proposal_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The hash of the reviewed content a proposal was asked for; one proposal per hash."""
    capture_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "owner_user_id", "request_key", name="uq_browser_teaching_request"
        ),
        CheckConstraint(
            "status IN ('recording', 'paused', 'review', 'discarded', 'expired', 'proposing', 'proposed')",
            name="state",
        ),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint(
            "jsonb_typeof(sanitized_events) = 'array' AND jsonb_array_length(sanitized_events) <= 500 "
            "AND octet_length(sanitized_events::text) <= 131072",
            name="events",
        ),
        CheckConstraint(
            "jsonb_typeof(allowed_origins) = 'array' AND jsonb_array_length(allowed_origins) <= 10",
            name="origins",
        ),
        CheckConstraint(
            "status NOT IN ('discarded', 'expired') OR "
            "(sanitized_events = '[]'::jsonb AND allowed_origins = '[]'::jsonb AND title = '' "
            "AND review = '[]'::jsonb AND proposal_name IS NULL AND source_hash IS NULL)",
            name="erased",
        ),
        CheckConstraint(
            "jsonb_typeof(review) = 'array' AND jsonb_array_length(review) <= 500 "
            "AND octet_length(review::text) <= 131072",
            name="review",
        ),
        CheckConstraint(
            "status <> 'proposed' OR (sanitized_events = '[]'::jsonb AND review = '[]'::jsonb)",
            name="proposed",
        ),
        CheckConstraint(
            "status NOT IN ('proposing', 'proposed') OR (source_hash IS NOT NULL AND proposal_name IS NOT NULL)",
            name="proposing",
        ),
        Index("ix_browser_teaching_owner", "organization_id", "owner_user_id", "created_at"),
        Index("ix_browser_teaching_expiry", "expires_at"),
        Index(
            "uq_browser_teaching_active_view",
            "organization_id",
            "run_id",
            "call_id",
            unique=True,
            postgresql_where=text("status IN ('recording', 'paused')"),
        ),
    )

    def __repr__(self) -> str:
        return f"<BrowserTeachingSession(id={self.id}, status={self.status}, revision={self.revision})>"
