"""A browser or installed PWA that agreed to receive Web Push (#2097).

One row per subscription a browser handed the console: the push service's
endpoint and the two keys the message is encrypted to (RFC 8291). They are
stored as given rather than sealed: without this deployment's VAPID private
key - which is sealed - a push service refuses a message to the endpoint, so
the row alone lets nobody reach the person.

A row whose endpoint the push service answers 404 or 410 is deleted at once:
the browser unsubscribed, or the person cleared its data, and there is nothing
to retry.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class PushSubscription(Base, TimestampMixin):
    """One browser's Web Push subscription, for one person."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    """The push service's URL for this browser. Unique: a browser that
    subscribes again, or is signed in as somebody else, replaces its row."""
    p256dh: Mapped[str] = mapped_column(String(128), nullable=False)
    auth: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """The sign-in that registered it, so the Devices list can say which of
    them receive push (#2305). Null for a row registered before it was kept."""
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PushSubscription(id={self.id}, user_id={self.user_id})>"
