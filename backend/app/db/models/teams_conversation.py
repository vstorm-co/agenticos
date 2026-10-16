"""Where a Teams bot can post: one row per conversation it has been in (#1985).

A Teams reply is an HTTP call to the Bot Connector service that sent the
activity, at the `serviceUrl` it carried, into the conversation it named. A
reply right after the message could take both off the activity; anything later
cannot - a run parked on an approval and resumed from the console, a trigger
posting its result. So every activity the bot receives records its
conversation here, and a post reads the reference back.

`key` is what the rest of the platform calls the conversation. A Teams
conversation id is long - a personal chat's runs past a hundred characters - and
full of colons, while `channel_sessions.platform_chat_id` is a hundred
characters and the channel layer reads a colon as "channel, then thread". A
hash of the id fits both.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TeamsConversation(Base, TimestampMixin):
    """A Teams conversation one bot has been in, and the service that hosts it."""

    __tablename__ = "teams_conversations"
    __table_args__ = (UniqueConstraint("bot_id", "key", name="uq_teams_conversation_bot_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("channel_bots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    """`teams.conversation_key(conversation_id)` - the id the channel layer uses."""

    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    """Teams' own id, without a `;messageid=` thread suffix."""

    service_url: Mapped[str] = mapped_column(String(500), nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    """`personal`, `groupChat` or `channel`, as Teams names them."""

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """The channel or chat's name where Teams sends one, for the console's picker."""

    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<TeamsConversation(bot={self.bot_id}, key={self.key}, type={self.conversation_type})>"
        )
