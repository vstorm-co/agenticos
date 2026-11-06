"""A person's explicit, organization-bound private notification destination."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class NotificationRoute(Base, TimestampMixin):
    __tablename__ = "notification_routes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Relinking an account must never revive an old delivery permission.
    identity_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    bot_generation: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", "channel", name="uq_notification_route_owner"
        ),
        CheckConstraint(
            "channel IN ('slack', 'telegram', 'mattermost', 'teams', 'sms', 'imessage', 'discord')",
            name="ck_notification_routes_channel",
        ),
    )

    def __repr__(self) -> str:
        return f"<NotificationRoute(id={self.id}, channel={self.channel})>"
