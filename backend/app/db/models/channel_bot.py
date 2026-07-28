"""ChannelBot model - one row per registered bot instance (PostgreSQL async)."""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.services.channels.base import DEFAULT_ACCESS_POLICY


class ChannelBot(Base, TimestampMixin):
    """Registered bot instance for a messaging platform."""

    __tablename__ = "channel_bots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # A bot belongs to exactly one organization: every conversation it opens is
    # stamped with this org, which is what lets conversations.organization_id be
    # NOT NULL even though channel conversations have no user.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Envelope produced by app.core.vault.seal, bound to organization_id - the
    # column name predates the vault and is kept so a rename is not smuggled
    # into a security change.
    token_encrypted: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Which vault master key sealed the token, so a staged rotation can tell
    # which rows it has already moved.
    secret_key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The platform's own base URL, for platforms that are self-hosted. Slack and
    # Telegram have one address for everybody; a Mattermost bot belongs to a
    # particular server and cannot post anywhere without knowing which.
    api_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_policy: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_ACCESS_POLICY),
    )
    ai_model_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_prompt_override: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ChannelBot(id={self.id}, platform={self.platform}, name={self.name})>"
