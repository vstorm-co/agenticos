"""ChannelSession model - active bot + chat conversation thread (PostgreSQL async)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChannelSession(Base, TimestampMixin):
    """Active conversation thread between a bot and a chat."""

    __tablename__ = "channel_sessions"
    __table_args__ = (
        UniqueConstraint("bot_id", "platform_chat_id", name="uq_channel_session_bot_chat"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    platform_chat_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    chat_type: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    """How many turns this chat has had, for "report usage every n messages".

    Counted here rather than by counting rows in `messages`: "every tenth
    message" is a question about *this* chat, the answer is needed on every turn
    of it, and a `COUNT(*)` per turn on a table that grows forever is a cost that
    only goes up. Incremented in the same `UPDATE` that already records the
    activity, so it costs nothing extra.
    """

    def __repr__(self) -> str:
        return f"<ChannelSession(id={self.id}, bot_id={self.bot_id}, platform_chat_id={self.platform_chat_id})>"
