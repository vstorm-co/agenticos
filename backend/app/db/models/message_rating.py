"""Message rating model for user feedback on AI responses.

This module is only imported when JWT auth is enabled (see
`app/db/models/__init__.py` and `alembic/env.py`).
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.channel_identity import ChannelIdentity
    from app.db.models.conversation import Message
    from app.db.models.user import User


class MessageRating(Base, TimestampMixin):
    """User rating for AI assistant messages."""

    __tablename__ = "message_ratings"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_user_rating"),
        UniqueConstraint("message_id", "channel_identity_id", name="uq_message_channel_rating"),
        CheckConstraint(
            "(user_id IS NOT NULL) <> (channel_identity_id IS NOT NULL)", name="ck_rating_author"
        ),
        CheckConstraint("rating IN (1, -1)", name="ck_rating_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    channel_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_identities.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    channel_identity: Mapped[ChannelIdentity | None] = relationship("ChannelIdentity")
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or -1
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[Message] = relationship(
        "Message",
        foreign_keys="MessageRating.message_id",
    )
    user: Mapped[User | None] = relationship(
        "User",
        foreign_keys="MessageRating.user_id",
    )

    def __repr__(self) -> str:
        return f"<MessageRating(id={self.id}, rating={self.rating})>"
