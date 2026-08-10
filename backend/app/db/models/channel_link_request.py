"""ChannelLinkRequest - a chat account waiting to be claimed by a person.

A run started from Slack, Telegram or Mattermost belongs to somebody: the budget
it spends, what it may read and the audit entry it writes are all theirs. A
message arrives carrying a platform user id and nothing else, so the two have to
be connected - and the connection can only be confirmed by whoever is
authenticated, which is a browser session and never a chat.

So the bot mints one of these and answers with a URL. The person clicks it, is
already signed in, and confirms. Nothing is typed and no command is needed, which
matters more than it sounds: the direction used to run the other way - a code
minted in the dashboard and typed at the bot - and Mattermost parses a leading
`/` itself, so the command carrying it never arrived. A flow whose first step is
"copy this string into another application" is one people ask for help with.

**The token is a bearer credential**: whoever opens the URL claims this chat
account. That is why it is only ever sent in a direct message, why it lives for
minutes, and why it is spent on first use.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChannelLinkRequest(Base, TimestampMixin):
    """One outstanding claim on a chat account, waiting for a browser."""

    __tablename__ = "channel_link_requests"
    __table_args__ = (
        # One outstanding request per chat account: asking again replaces it, so
        # a URL that scrolled out of view stops working rather than lingering.
        UniqueConstraint("platform", "platform_user_id", name="channel_link_requests_identity_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unguessable and unique: it is the whole of the authorisation, so two rows
    # sharing one would make which account gets claimed a matter of row order.
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Shown on the confirmation page, so somebody can see *which* chat account
    # they are about to become - a token alone would ask them to trust a URL.
    platform_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    platform_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ChannelLinkRequest(platform={self.platform}, "
            f"platform_user_id={self.platform_user_id})>"
        )
