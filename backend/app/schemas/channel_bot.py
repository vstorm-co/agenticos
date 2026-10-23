"""Channel bot, identity, and session schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, computed_field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.urls import ServiceAddress
from app.services.channels.webhooks import inbound_command_url, inbound_webhook_url
from app.services.speech_to_text import is_offered


class AccessPolicy(BaseSchema):
    """Bot access control policy."""

    mode: Literal["open", "whitelist", "jwt_linked", "group_only"] = "open"
    whitelist: list[str] = []
    allowed_groups: list[str] = []
    require_link: bool = False
    rate_limit_rpm: int = 10
    denied_message: str = "You are not authorised to use this bot."


class UsageReporting(BaseSchema):
    """When an agent says what a turn cost, and when it only records it.

    Lives on the binding rather than on the bot - see
    :class:`app.db.models.agent_exposure.AgentExposure` - so it is declared here
    beside `AccessPolicy` only because both are shapes stored as JSON on the
    channel side. They answer different questions and belong to different people:
    that one decides who may talk to the bot and is the operator's, this one
    decides how talkative the agent is about spending and is its author's.
    """

    mode: Literal["off", "always", "near_limit", "every_n"] = Field(
        default="near_limit",
        description=(
            "off records it and stays quiet; always reports every turn; "
            "near_limit reports once the budget or the workspace passes the "
            "threshold; every_n reports every n-th turn of a chat."
        ),
    )
    near_limit_percent: int = Field(
        default=80,
        ge=1,
        le=100,
        description="What near_limit compares the budget and the workspace against",
    )
    every_n: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="The n in every_n, counted per chat rather than per bot",
    )


ACK_REACTION_PATTERN = r"^[a-z0-9_+\-]{1,64}$"
"""An emoji's name as Slack and Mattermost spell it, without the colons."""


StepDisplay = Literal["timeline", "plan"]
"""How a streamed answer shows its tool calls: one row each, or one plan."""


TEAMS_ID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
"""An Entra app id or tenant id: a GUID."""


class ChannelBotCreate(BaseSchema):
    """Schema for creating a channel bot."""

    platform: str = Field("telegram", max_length=20)
    name: str = Field(..., max_length=255)
    token: str = Field(..., min_length=10, max_length=500)
    webhook_mode: bool = False
    webhook_url: str | None = None
    api_base_url: ServiceAddress | None = Field(
        default=None,
        max_length=500,
        description=(
            "The bot's own Mattermost server, e.g. https://mattermost.acme.internal. "
            "Required for Mattermost and refused for the others, which have one "
            "address for everybody."
        ),
    )
    webhook_secret: str | None = Field(
        default=None,
        min_length=8,
        max_length=255,
        description=(
            "The shared secret an inbound webhook is authenticated against. Paste "
            "the token Mattermost shows when the outgoing webhook is created; for "
            "Telegram, leave it empty and one is generated and handed over when "
            "the webhook is registered. Sealed in the vault, never returned."
        ),
    )
    access_policy: AccessPolicy = Field(default_factory=AccessPolicy)
    slack_signing_secret: str | None = Field(
        default=None,
        min_length=8,
        max_length=255,
        description=(
            "This Slack app's signing secret - inbound events are verified "
            "with it. Slack bots only; sealed in the vault, never returned."
        ),
    )
    slack_app_token: str | None = Field(
        default=None,
        min_length=8,
        max_length=500,
        description="This Slack app's xapp- token, for Socket Mode. Slack bots only.",
    )
    command_token: str | None = Field(
        default=None,
        min_length=8,
        max_length=255,
        description=(
            "The token Mattermost shows for the `/agent` slash command, which every "
            "request from it carries. Mattermost bots only; sealed, never returned."
        ),
    )
    teams_app_id: str | None = Field(
        default=None,
        pattern=TEAMS_ID_PATTERN,
        description=(
            "The Microsoft App ID of the Teams bot's Azure Bot registration. Teams "
            "bots only; the token is that app's client secret."
        ),
    )
    teams_tenant_id: str | None = Field(
        default=None,
        pattern=TEAMS_ID_PATTERN,
        description="The Entra tenant the single-tenant Azure Bot is registered in. Teams only.",
    )
    stream_answers: bool = Field(
        default=True,
        description=(
            "Stream answers natively where the platform draws them (Slack), with a "
            "step per tool call; otherwise a message is edited into place."
        ),
    )
    step_display: StepDisplay = Field(
        default="timeline",
        description="Show a streamed answer's tool calls as a `timeline` or as one `plan`.",
    )
    rate_answers: bool = Field(
        default=True, description="Put thumbs under a finished answer to rate it."
    )
    ack_reaction: str | None = Field(
        default=None,
        pattern=ACK_REACTION_PATTERN,
        description=(
            "The emoji the bot reacts to a question with as it arrives, by the "
            "platform's name for it (`eyes`). Slack and Mattermost; null for none."
        ),
    )
    transcribe_voice_notes: bool = Field(
        default=True,
        description=(
            "Whether voice notes are transcribed at all. On by default, with the "
            "pair below or - with none - the agent's or organization's engine; "
            "off never transcribes, and a pair sent with it is refused."
        ),
    )
    speech_to_text_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Which provider transcribes voice notes, from the speech-to-text "
            "catalog. Null inherits the agent's or the organization's."
        ),
    )
    speech_to_text_model: str | None = Field(
        default=None,
        max_length=255,
        description="Which of that provider's transcription models to use.",
    )
    speech_to_text_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The vault key the bot's own pair is sent with: an organization-visible "
            "API key whose purpose is the provider. Required with a pair, refused "
            "without one."
        ),
    )

    @model_validator(mode="after")
    def _transcription_is_a_pair_the_catalog_lists(self) -> ChannelBotCreate:
        """Both halves or neither, and the catalog has to list the model.

        A provider with no model has nothing to call and a model with no provider
        has nowhere to send it, so one without the other is a setting that reads as
        configured and does nothing - the state somebody debugs by sending voice
        notes into silence.

        The model is checked against the catalog rather than left free text, unlike
        the chat model field: the endpoint refuses an unknown model with an error
        only the sender waiting for a reply ever sees, so a typo belongs on the
        form. Same bargain `ImageGenerationConfig` makes, and for the same reason.
        """
        provider, model = self.speech_to_text_provider, self.speech_to_text_model
        if (provider is None) != (model is None):
            raise ValueError(
                "Transcription needs a provider and a model together - one without "
                "the other is a setting that cannot run"
            )
        if provider is not None and model is not None and not is_offered(provider, model):
            raise ValueError(
                f"'{model}' is not a transcription model this deployment offers for {provider}"
            )
        if provider is None and self.speech_to_text_secret_id is not None:
            raise ValueError(
                "A transcription key goes with the bot's own provider and model - "
                "an inheriting bot uses the key of the level it inherits from"
            )
        return self

    @model_validator(mode="after")
    def _a_teams_bot_carries_its_registration(self) -> ChannelBotCreate:
        """A Teams bot is saved with its app and tenant, and nothing else is (#1985).

        Without both it can neither sign in to answer nor recognise a token meant
        for it. And it is always a webhook bot: Teams posts every activity to the
        bot's endpoint, and there is nothing to poll.
        """
        teams = self.platform == "teams"
        if teams and (self.teams_app_id is None or self.teams_tenant_id is None):
            raise ValueError("A Teams bot needs its Azure Bot's app ID and tenant ID")
        if not teams and (self.teams_app_id is not None or self.teams_tenant_id is not None):
            raise ValueError(f"An app and tenant ID are for a Teams bot, not a {self.platform} bot")
        if teams:
            self.webhook_mode = True
        return self

    @model_validator(mode="after")
    def _a_self_hosted_bot_carries_its_server(self) -> ChannelBotCreate:
        """A Mattermost bot is saved with its server's URL, or not saved.

        Mattermost is self-hosted: there is no api.mattermost.com, so a bot that
        does not know its own server cannot post a reply, cannot open the event
        stream and cannot fetch a file somebody attached. Refusing here is what
        the adapter's own docstring promises - that a missing server URL is
        reported when the bot is saved, rather than the first time somebody
        messages it - and for a year it promised a check that did not exist:
        the field was on the model and on no schema, so every Mattermost bot
        ever created was registered and deaf.

        The other direction is the same rule as the Slack credentials below it.
        Telegram and Slack have one address for everybody, so a server URL on
        one of those is a value nothing will ever read.
        """
        if self.platform == "mattermost" and self.api_base_url is None:
            raise ValueError(
                "A Mattermost bot needs its server's URL - it is self-hosted, so "
                "there is no default address to fall back to"
            )
        if self.platform != "mattermost" and self.api_base_url is not None:
            raise ValueError(
                f"A server URL is for a self-hosted platform - a {self.platform} bot "
                "has one address for everybody"
            )
        return self


class ChannelBotUpdate(BaseSchema):
    """Schema for updating a channel bot (all fields optional).

    The Slack credentials distinguish omission from an explicit null: omitted
    leaves the stored value, null clears it. So does the transcription pair -
    null clears it, which since #1797 means "inherit", not "off". Off is
    `transcribe_voice_notes: false`, which refuses an explicit null.
    """

    name: str | None = Field(default=None, max_length=255)
    token: str | None = Field(default=None, min_length=10, max_length=500)
    webhook_mode: bool | None = None
    webhook_url: str | None = None
    api_base_url: ServiceAddress | None = Field(default=None, max_length=500)
    webhook_secret: str | None = Field(default=None, min_length=8, max_length=255)
    access_policy: AccessPolicy | None = None
    is_active: bool | None = None
    slack_signing_secret: str | None = Field(default=None, min_length=8, max_length=255)
    slack_app_token: str | None = Field(default=None, min_length=8, max_length=500)
    transcribe_voice_notes: bool | None = None
    command_token: str | None = Field(default=None, min_length=8, max_length=255)
    ack_reaction: str | None = Field(default=None, pattern=ACK_REACTION_PATTERN)
    stream_answers: bool | None = None
    step_display: StepDisplay | None = None
    rate_answers: bool | None = None
    speech_to_text_provider: str | None = Field(default=None, max_length=32)
    speech_to_text_model: str | None = Field(default=None, max_length=255)
    speech_to_text_secret_id: UUID | None = None

    @model_validator(mode="after")
    def _a_named_transcription_model_is_one_that_exists(self) -> ChannelBotUpdate:
        """Checked where both are given, which is how the form sends them.

        A patch may legitimately carry one alone - the pairing is enforced against
        the stored row in the service, which is the only place that knows what the
        other half currently is. What can be decided here is whether a model this
        request names is one the catalog lists.
        """
        provider, model = self.speech_to_text_provider, self.speech_to_text_model
        if provider is not None and model is not None and not is_offered(provider, model):
            raise ValueError(
                f"'{model}' is not a transcription model this deployment offers for {provider}"
            )
        return self


class BotAgent(BaseSchema):
    """An agent that answers on one bot, as the channels listing names it."""

    id: UUID
    name: str
    slug: str
    has_avatar: bool


class InheritedSpeechToTextRead(BaseSchema):
    """What a bot's voice notes go to when it inherits rather than names a pair.

    For the hint beside "Inherit" in the bot's form: which provider and model,
    and whether the bot's agent or its organization chose them. The key is
    the inherited level's own and is not named - only whether one is usable,
    so the form can say the level still needs one.
    """

    provider: str
    model: str
    has_key: bool = False
    """Whether the inherited level names a key that is still usable for it."""
    language: str | None = None
    pair_source: Literal["agent", "organization"]
    language_source: Literal["agent", "organization"] | None = None
    agent_name: str | None = None
    """The agent this bot serves, through whose spec the pair may have come."""


class ChannelConnectionRead(BaseSchema):
    """Whether this bot's inbound connection is actually up.

    Absent where nothing is known - no Redis, or no supervisor has touched this
    bot since the entry expired. Unknown is its own answer: claiming healthy is
    the defect this reports on, and claiming broken is the same defect pointing
    the other way.
    """

    state: Literal["up", "down"]
    reason: str | None = None
    """What an operator can do about it, never a vendor exception's text."""


class ChannelBotRead(BaseSchema):
    """Schema for reading a channel bot (token_encrypted is never returned)."""

    id: UUID
    platform: str
    name: str
    is_active: bool
    webhook_mode: bool
    webhook_url: str | None
    # An address, not a credential: the panel has to show which server a bot
    # belongs to, and there is nothing secret about a hostname the operator
    # typed. The secret that goes with it is `has_webhook_secret` below.
    api_base_url: str | None = None
    access_policy: AccessPolicy
    # Booleans, never the values: the panel needs "is this configured", and a
    # response is the way a sealed credential usually escapes.
    has_webhook_secret: bool = False
    has_slack_signing_secret: bool = False
    has_slack_app_token: bool = False
    transcribe_voice_notes: bool = True
    """Whether voice notes are transcribed here at all; off wins over every pair."""
    has_command_token: bool = False
    # Identifiers, not secrets: the console builds the Teams app package from them.
    teams_app_id: str | None = None
    teams_tenant_id: str | None = None
    ack_reaction: str | None = None
    stream_answers: bool = True
    step_display: StepDisplay = "timeline"
    rate_answers: bool = True

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented form
    @property
    def command_url(self) -> str | None:
        """The request URL for a Mattermost bot's `/agent` slash command, to paste there."""
        return inbound_command_url(str(self.id)) if self.platform == "mattermost" else None

    @computed_field  # type: ignore[prop-decorator]  # pydantic's documented form
    @property
    def messaging_endpoint(self) -> str | None:
        """A Teams bot's messaging endpoint, to paste into its Azure Bot resource (#1985)."""
        return inbound_webhook_url("teams", self.id) if self.platform == "teams" else None

    speech_to_text_provider: str | None = None
    speech_to_text_model: str | None = None
    """Which model transcribes voice notes here, or null to inherit one.

    Read back plainly: a provider id and a model id are choices somebody made,
    not credentials.
    """
    speech_to_text_secret_id: UUID | None = None
    """The vault key the bot's own pair is sent with, by id - never its value.
    Null with a pair means the key was deleted, and voice notes wait for another."""

    inherited_speech_to_text: InheritedSpeechToTextRead | None = None
    """What "inherit" resolves to for this bot, on the single-bot read only.

    Answered whatever the bot is set to now, because the form asks it before
    somebody switches to inherit. Null on the listing - resolving it reads each
    bot's agent version, which a page of bots should not pay for - and null
    where nothing resolves: no agent or organization provider, or no agent
    bound to the bot at all.
    """

    connection: ChannelConnectionRead | None = None
    """The state of the socket this bot receives on, for a polling bot.

    A webhook bot holds no connection and reports none. A polling bot whose
    stream never opened used to look identical to a working one: the row showed
    `Polling`, an agent bound and nothing else, while the reason sat in a
    container log (#1351).
    """

    agents: list[BotAgent] = []
    """Who answers here, from the active bindings.

    A bot with none is registered and silent, which is the state somebody is
    trying to explain when they open this page - and the listing said nothing
    about it at all. Not narrowed per agent: this endpoint already demands
    `channels:manage`, and the vault's `used_by` names agents the same way for
    the same reason.
    """

    created_at: datetime
    updated_at: datetime | None = None


class ChannelBotList(BaseSchema):
    """Paginated list of channel bots."""

    items: list[ChannelBotRead]
    total: int


class ChannelLinkRequestRead(BaseSchema):
    """Which chat account a link URL is about.

    Shown on the confirmation page before anything is joined: a page that says
    only "connect your account" asks somebody to trust a URL, and this is a URL
    that arrived in a chat.
    """

    platform: str
    platform_username: str | None = None
    platform_display_name: str | None = None
    expires_at: datetime


class LinkedAgent(BaseSchema):
    """An agent this chat account can reach, as a person recognises one."""

    id: UUID
    name: str
    slug: str
    has_avatar: bool


class LinkedPlace(BaseSchema):
    """One bot a chat account has been used with, and what answers there.

    A `ChannelIdentity` is keyed on the platform and the account, never on a
    bot - so "Mattermost" is the whole of what the row could say about itself,
    and on a deployment with two Mattermost servers that is not enough to know
    which company's chat somebody just connected. The sessions hanging off the
    identity are the only record of where it has actually been used, and this is
    that record: which bot, on which host, answering as which agents.
    """

    bot_id: UUID
    bot_name: str
    host: str | None = None
    """The server this bot lives on, for the platforms that have one.

    Mattermost is self-hosted, so the host *is* the identifying fact - the
    hostname alone, never the configured URL: that value is an operator's and
    may carry a path or a port nobody needs to read here. `None` on Slack and
    Telegram, where every bot is on the same SaaS and the bot's name is the
    place.
    """

    agents: list[LinkedAgent] = []
    """What answers on this bot, narrowed to what the reader may see.

    Not simply every active binding: an agent somebody may not read is one they
    should not learn the name of from their own profile page, and a list here
    would be an enumeration endpoint wearing a friendly hat.
    """


class ChannelIdentityRead(BaseSchema):
    """Schema for reading a channel identity."""

    id: UUID
    user_id: UUID | None = None
    platform: str
    platform_user_id: str
    platform_username: str | None = None
    platform_display_name: str | None = None
    is_active: bool
    created_at: datetime
    places: list[LinkedPlace] = []
    """Where this account has been used, empty until it has been used anywhere."""


class ChannelIdentityList(BaseSchema):
    """The chat accounts one person has connected."""

    items: list[ChannelIdentityRead]
    total: int


class ChannelSessionRead(BaseSchema):
    """Schema for reading a channel session."""

    id: UUID
    bot_id: UUID
    identity_id: UUID
    conversation_id: UUID | None = None
    platform_chat_id: str
    chat_type: str
    is_active: bool
    last_message_at: datetime | None = None
    created_at: datetime


class ChannelSessionList(BaseSchema):
    """Paginated list of channel sessions."""

    items: list[ChannelSessionRead]
    total: int


class TeamsConversationRead(BaseSchema):
    """A Teams channel or group chat a bot is in - somewhere a trigger can post (#1985)."""

    id: UUID
    bot_id: UUID
    name: str | None = None
    conversation_type: Literal["channel", "groupChat"]
    last_activity_at: datetime


class TeamsConversationList(BaseSchema):
    items: list[TeamsConversationRead]
