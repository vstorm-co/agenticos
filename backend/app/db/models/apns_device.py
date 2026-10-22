"""An iPhone that agreed to receive push through Apple's service (#2097).

One row per device token the app handed the console after the person allowed
notifications. The token is stored as given: a message to it needs this
deployment's APNs key - sealed on the deployment's settings row - so the row
alone lets nobody reach the person.

A token APNs answers 410 (unregistered) or 400 `BadDeviceToken` for is deleted
at once: the app was removed, or the token belongs to another environment, and
there is nothing to retry.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ApnsDevice(Base, TimestampMixin):
    """One iPhone's APNs device token, for one person."""

    __tablename__ = "apns_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    """The device token, hex. Unique: an iPhone signed in as somebody else
    replaces its row."""
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ApnsDevice(id={self.id}, user_id={self.user_id})>"
