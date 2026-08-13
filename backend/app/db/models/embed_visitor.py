"""One returning visitor to a hosted page, and the thread they left open.

A widget keys a conversation to a visitor for the life of a socket, which is the
right promise for a bubble somebody opens on a pricing page. **A link somebody
bookmarks is a stronger one**: coming back to it and finding an empty thread is
the difference between a page and a chat window, and it is the part of #517 that
a hosted page exists for.

So the mapping is a row, the way a channel thread's is (`channel_sessions`, one
per bot and chat). It is not a column on `conversations`: what a visitor is
belongs to the surface that admitted them, and one surface's identity model has
no business on the table every surface writes to.

**The visitor key is a bearer credential and has to be read as one.** Whoever
holds it resumes the conversation it names, including everything already said in
it, so it is minted with the same unguessability as the embed's public key and
never derived from anything about the person. In `jwt` mode there is no row here
at all - the token's subject *is* the identity, and a second one would be a
weaker way to answer a question already answered.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EmbedVisitor(Base, TimestampMixin):
    """The conversation one visitor to one embed comes back to."""

    __tablename__ = "embed_visitors"
    __table_args__ = (UniqueConstraint("embed_id", "visitor_key", name="uq_embed_visitor_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    embed_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_embeds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visitor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    """What the page kept in `localStorage`. Unguessable, and nothing about them."""

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """`SET NULL` rather than `CASCADE`: a conversation deleted by a retention
    sweep must leave the visitor able to start a new one, not delete the visitor.
    """

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When this key was last used, so a retention policy has something to read.

    Nothing enforces one yet, and a row nobody can date is a row nobody can
    expire - which is how "we keep it for as long as the link works" becomes "for
    ever" without anybody deciding it.
    """

    def __repr__(self) -> str:
        return f"<EmbedVisitor(embed={self.embed_id}, conversation={self.conversation_id})>"
