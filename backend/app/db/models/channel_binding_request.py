"""A request to bind an agent to a bot that answers people with no account (#2076).

A bot on a public line answers customers who never linked an account, so who may put an
agent behind it is a decision for someone who holds `channels:manage`. A Builder who may
publish the agent asks instead, and one table holds the three things they can ask for:

- `bind`: serve the bot with an agent, which it has none of.
- `environment`: move the existing binding to another named environment.
- `resume`: turn a paused binding back on.

A request is pending until a holder of `channels:manage` decides it, and it is voided when
what it asked about no longer stands: the same person asking again, the line closing, or
another agent taking the bot.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

MAX_NOTE_LENGTH = 500


class BindingRequestKind(StrEnum):
    BIND = "bind"
    ENVIRONMENT = "environment"
    RESUME = "resume"


class BindingRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    VOIDED = "voided"


class BindingVoidReason(StrEnum):
    """Why a pending request stopped being one without anybody deciding it."""

    REPLACED = "replaced"
    """The same person asked again."""
    LINE_CLOSED = "line_closed"
    """The bot stopped answering people with no account, so nothing needs the approval."""
    BOT_TAKEN = "bot_taken"
    """Another agent is bound to the bot, so what was asked is not what would apply."""


class ChannelBindingRequest(Base, TimestampMixin):
    """One person's request about one bot's binding."""

    __tablename__ = "channel_binding_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_bot_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # The binding an `environment` or `resume` request is about; none for `bind`.
    exposure_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_exposures.id", ondelete="CASCADE"), nullable=True
    )
    # The environment a `bind` or `environment` request asks for; none means the default.
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_environments.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # The membership they asked under, as a number rather than a key: re-inviting
    # someone makes a new one, and what they asked before is not theirs to stand on.
    requester_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Shown to whoever decides it, never in a notification.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=BindingRequestStatus.PENDING.value,
        server_default=BindingRequestStatus.PENDING.value,
    )
    void_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('bind', 'environment', 'resume')", name="ck_channel_binding_request_kind"
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'declined', 'voided')",
            name="ck_channel_binding_request_status",
        ),
        CheckConstraint(
            f"note IS NULL OR char_length(note) <= {MAX_NOTE_LENGTH}",
            name="ck_channel_binding_request_note",
        ),
        # Only a new binding has no binding to point at.
        CheckConstraint(
            "(kind = 'bind') = (exposure_id IS NULL)", name="ck_channel_binding_request_exposure"
        ),
        # One pending request per person and bot: a newer one replaces the older.
        Index(
            "uq_channel_binding_request_pending",
            "channel_bot_id",
            "requester_user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ChannelBindingRequest(bot={self.channel_bot_id}, kind={self.kind}, "
            f"status={self.status})>"
        )
