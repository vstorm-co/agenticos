"""ChannelBot model - one row per registered bot instance (PostgreSQL async)."""

import uuid

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, true
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
    # A Teams bot's Azure Bot registration (#1985): the Entra app it signs in as
    # and the tenant it is registered in. Identifiers, not credentials - the
    # client secret is `token_encrypted` - and the audience every inbound Bot
    # Connector token is checked against. NULL on other platforms.
    teams_app_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    teams_tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The token Mattermost gives a slash command when it is created, which every
    # `/agent` request carries (#2084). Sealed like the rest; Mattermost bots only.
    command_token_encrypted: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # The emoji the bot reacts to a question with the moment it arrives (#2084),
    # by the platform's own name for it - `eyes`. Null reacts with nothing.
    ack_reaction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Whether answers stream natively where the platform can draw them (Slack),
    # rather than as a placeholder edited into place - and, there, whether the
    # tool calls read as a timeline of steps or as one plan. A switch rather than
    # always-on: a workspace that finds the steps noisy turns them off.
    stream_answers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    step_display: Mapped[str] = mapped_column(
        String(16), nullable=False, default="timeline", server_default="timeline"
    )
    # Whether a finished answer carries thumbs to rate it.
    rate_answers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    transcribe_voice_notes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    """Whether this bot transcribes voice notes at all (#1797).

    Off means never, whatever the agent or the organization configure. On, the
    pair below decides: this bot's own, or - with none - the one its agent or
    its organization resolves to (`app/services/speech_to_text_settings.py`).

    A switch of its own rather than "null pair is off", because null now has a
    job: it is what inherits. On by default, so a bot registered from the CLI
    or by an older API client inherits too; cost stays the organization's to
    decide, because with no provider on the agent or the organization nothing
    is transcribed. `0151_bot_transcription_switch.py` turned it off for every
    bot that had no pair before, so none of them started transcribing on
    upgrade.
    """

    speech_to_text_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    speech_to_text_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Which model turns a voice note into text here, or null to inherit one.

    A pair rather than one string, because the provider decides where the request
    goes and the model decides what answers - the same split
    `ImageGenerationConfig` settled on after carrying an SDK prefix in one
    enumerated field and needing a migration to take it apart again. Both or
    neither, which `ck_channel_bot_speech_pair` holds.

    Two columns rather than a key in `access_policy`: this is not a policy, and a
    JSONB field is the place a value goes when nobody wants to write a migration -
    which is how a rule ends up being narrowed on a column that already holds rows
    that break it.

    Null inherits the agent's or the organization's pair, and only while
    `transcribe_voice_notes` is on. It used to mean off; that meaning moved to
    the switch.
    """

    speech_to_text_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organization_secrets.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The vault key this bot's own pair is sent with, or null with no pair.

    An org-visible `api_key` whose purpose is the provider: a bot's voice notes
    are paid for on behalf of whoever writes to it, so a member's private key
    may not pay for them. Named rather than looked up, and it travels with the
    pair - an inheriting bot takes the inherited level's key with its pair, and
    never this one. SET NULL on delete: the bot keeps its pair and reads as
    "choose a key" until somebody does.
    """

    access_policy: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: dict(DEFAULT_ACCESS_POLICY),
    )

    __table_args__ = (
        CheckConstraint(
            "(speech_to_text_provider IS NULL) = (speech_to_text_model IS NULL)",
            name="ck_channel_bot_speech_pair",
        ),
        CheckConstraint(
            "speech_to_text_secret_id IS NULL OR speech_to_text_provider IS NOT NULL",
            name="ck_channel_bot_speech_key_needs_pair",
        ),
    )

    @property
    def has_webhook_secret(self) -> bool:
        """Whether an inbound webhook can be authenticated - never the secret."""
        return self.webhook_secret_encrypted is not None

    @property
    def has_slack_signing_secret(self) -> bool:
        """Whether inbound Slack events can be verified - never the secret itself."""
        return self.slack_signing_secret_encrypted is not None

    @property
    def has_command_token(self) -> bool:
        """Whether `/agent` requests can be verified - never the token itself."""
        return self.command_token_encrypted is not None

    @property
    def has_slack_app_token(self) -> bool:
        """Whether Socket Mode (dev polling) can run - never the token itself."""
        return self.slack_app_token_encrypted is not None

    def __repr__(self) -> str:
        return f"<ChannelBot(id={self.id}, platform={self.platform}, name={self.name})>"
