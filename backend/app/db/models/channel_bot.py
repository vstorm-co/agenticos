"""ChannelBot model - one row per registered bot instance (PostgreSQL async)."""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.services.channels.base import DEFAULT_ACCESS_POLICY, DEFAULT_USAGE_REPORTING


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
    # The shared secret an inbound webhook is authenticated against - Telegram's
    # `X-Telegram-Bot-Api-Secret-Token`, Mattermost's outgoing-webhook token.
    # Sealed like the bot token and at the same `secret_key_version`: it is the
    # only thing standing between the internet and a run on this organization's
    # budget, and it sat in the clear beside three sealed columns until #22.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # A Slack bot's own app credentials, sealed like the token and at the same
    # `secret_key_version`. Per bot rather than per deployment: one row is one
    # Slack app, and a second workspace's app must not verify - or be verified
    # by - the first's secret. NULL on other platforms, and on Slack bots
    # registered before the credentials moved off the environment.
    slack_signing_secret_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    slack_app_token_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    access_policy: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_ACCESS_POLICY),
    )

    usage_reporting: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_USAGE_REPORTING),
    )
    """When this bot says what a turn cost, and when it only records it.

    Its own column rather than a key in `access_policy`, which decides who may
    talk to the bot - a reader who found "how loud is it about spending" in there
    would reasonably conclude the two are one policy, and the next person to
    narrow access would be editing the same JSON blob as the person tuning noise.

    JSON because the shape is a small set of related knobs that only ever move
    together: a mode, the threshold `near_limit` compares against, and the `n` in
    "every n". Columns for each would be three migrations to add a fourth mode.
    """

    @property
    def has_webhook_secret(self) -> bool:
        """Whether an inbound webhook can be authenticated - never the secret."""
        return self.webhook_secret_encrypted is not None

    @property
    def has_slack_signing_secret(self) -> bool:
        """Whether inbound Slack events can be verified - never the secret itself."""
        return self.slack_signing_secret_encrypted is not None

    @property
    def has_slack_app_token(self) -> bool:
        """Whether Socket Mode (dev polling) can run - never the token itself."""
        return self.slack_app_token_encrypted is not None

    def __repr__(self) -> str:
        return f"<ChannelBot(id={self.id}, platform={self.platform}, name={self.name})>"
