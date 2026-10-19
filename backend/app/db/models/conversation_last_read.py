"""When one person last read a conversation."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationLastRead(Base):
    """A row per (reader, conversation): the moment they last had it open.

    The reader's, for the reason a favourite is: a shared thread and a channel
    thread have several readers, and one person opening it must not mark it read
    for the rest. A conversation is unread for somebody while its newest answer is
    newer than this. Both keys cascade, as a favourite's do.
    """

    __tablename__ = "conversation_reads"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationLastRead(user_id={self.user_id}, "
            f"conversation_id={self.conversation_id}, read_at={self.read_at})>"
        )
