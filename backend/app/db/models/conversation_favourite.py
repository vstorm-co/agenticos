"""One person's favourite conversation."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.conversation import Conversation
    from app.db.models.user import User


class ConversationFavourite(Base, TimestampMixin):
    """A row per (reader, conversation), and that is the whole design decision.

    A favourite is a property of the **reader**, not of the thread. A
    conversation can be shared (`ConversationShare`) and a channel thread has
    participants rather than an owner, so a boolean on `conversations` would let
    one person's star decide where the thread sits for everybody who can see it
    (#929).

    Both foreign keys cascade: a deleted account leaves no stars behind, and a
    deleted conversation cannot be starred by anybody. The pair is the primary
    key, so starring twice is a conflict rather than two rows, and the index the
    listing needs - "this reader's favourites" - is the key's own.
    """

    __tablename__ = "conversation_favourites"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    user: Mapped["User"] = relationship("User", foreign_keys="ConversationFavourite.user_id")
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", foreign_keys="ConversationFavourite.conversation_id"
    )

    def __repr__(self) -> str:
        return (
            f"<ConversationFavourite(user_id={self.user_id}, "
            f"conversation_id={self.conversation_id})>"
        )
