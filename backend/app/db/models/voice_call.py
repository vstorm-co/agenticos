"""One connection of a voice call, and what bounds it if nobody hangs it up (#54).

Written at setup and heartbeated every 15 s by the process holding the call. A
call over WebRTC is the provider's, not ours: the browser holds the audio, and
closing our sideband leaves it talking and billing (spike, live result 2). So
the row carries what a hang-up needs without the session - the provider's call
id and the key - and two clocks: `ended_at` (our side finished) and
`hung_up_at` (the provider confirmed). The reaper works on rows with no
`hung_up_at` whose heartbeat went stale or whose end was recorded.

Each reconnect is its own row and its own run, linked by `resume_of`, so a
call's time and budget carry over the chain while every connection stays
attributable. Call minutes are summed from these rows, never from run durations.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class VoiceEndReason(enum.StrEnum):
    """Why a call ended, in words Activity can show."""

    USER = "user"
    TIME_LIMIT = "time_limit"
    BUDGET = "budget"
    DISCONNECTED = "disconnected"
    REVOKED = "revoked"
    GUARDRAIL = "guardrail"
    ERROR = "error"
    SHUTDOWN = "shutdown"
    REAPED = "reaped"
    ABANDONED = "abandoned"
    """The reaper could not hang it up (its key is gone) and gave up after an hour,
    when the provider has ended every session by itself."""


class VoiceCall(Base, TimestampMixin):
    __tablename__ = "voice_calls"
    __table_args__ = (
        Index("ix_voice_calls_org_started", "organization_id", "started_at"),
        Index("ix_voice_calls_unhung", "heartbeat_at", postgresql_where=text("hung_up_at IS NULL")),
        CheckConstraint("transport IN ('webrtc', 'relay')", name="ck_voice_calls_transport"),
        CheckConstraint("surface IN ('web', 'embed')", name="ck_voice_calls_surface"),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('user', 'time_limit', 'budget', "
            "'disconnected', 'revoked', 'guardrail', 'error', 'shutdown', 'reaped', 'abandoned')",
            name="ck_voice_calls_end_reason",
        ),
        CheckConstraint("seconds >= 0", name="ck_voice_calls_seconds"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, not CASCADE: deleting an agent must neither give back the month's
    # minutes its calls used nor hide a live call from the reaper.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # SET NULL: the run is the money's record, the call row the minutes'. Either outlives the other.
    # Checked at commit rather than per row: deleting an agent cascades to its
    # runs and nulls this row's `agent_id` in one statement, and which of those
    # actions runs first depends on the order the constraints were created in -
    # checked at once, the `agent_id` update could meet a run already gone, before
    # its own `run_id` was nulled, and the delete was refused.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL", deferrable=True, initially="DEFERRED"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Indexed whole, not only its open calls: the embed's open-call count needs
    # the open ones, and an embed's delete (SET NULL) needs every one.
    embed_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_embeds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    surface: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(8), nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    resume_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("voice_calls.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The hash of the token this connection's `ready` gave its caller, which a
    # reconnect must present: the call id alone is not proof of being on the call.
    resume_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hung_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    guardrail_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<VoiceCall(id={self.id}, provider={self.provider}, ended_at={self.ended_at})>"
