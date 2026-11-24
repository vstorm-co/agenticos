"""One reader's bookmark on one message in a conversation."""

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ConversationMessagePin(Base, TimestampMixin):
    """Keep only the reader and message identity, never another transcript copy."""

    __tablename__ = "conversation_message_pins"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_conversation_message_pin_message",
        ),
        Index(
            "conversation_message_pins_user_conversation_created_at_idx",
            "user_id",
            "conversation_id",
            "created_at",
        ),
        Index(
            "conversation_message_pins_conversation_message_idx",
            "conversation_id",
            "message_id",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    def __repr__(self) -> str:
        return (
            f"<ConversationMessagePin(user_id={self.user_id}, "
            f"conversation_id={self.conversation_id}, message_id={self.message_id})>"
        )
