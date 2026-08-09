"""ChannelLinkCode - a short-lived claim that a chat account is a person's.

A run started from Slack, Telegram or Mattermost belongs to a *person*: the
budget it spends, the resources it may read and the audit entry it writes are all
theirs. A channel identity arrives with nothing but a platform user id, so
something has to connect the two, and that something has to be initiated from the
side that is already authenticated - the dashboard.

Hence a code: minted for the signed-in user, read back out by whoever types it
into a chat. It is a bearer credential for the duration of its life, which is why
that life is minutes rather than days and why it is single-use.

The code used to live on `channel_identities.link_code`, which is the wrong row
for it. That column could only hold a code for an identity that *already* had a
user, so `/link` was implemented as "copy the user from whichever identity holds
this code" - a second chat account linking a third, with no first. Nothing ever
wrote the column, so the whole command answered "invalid or expired" to every
code that was never generated (#10).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChannelLinkCode(Base, TimestampMixin):
    """One outstanding claim, waiting to be typed into a chat."""

    __tablename__ = "channel_link_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Unique because it is what a stranger types: two rows sharing a code would
    # make which account a chat identity joined a matter of row order.
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<ChannelLinkCode(user_id={self.user_id}, expires_at={self.expires_at})>"
