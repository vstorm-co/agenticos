"""Channel bot, identity, and session schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.urls import ServiceAddress
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
    speech_to_text_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Which provider transcribes voice notes, from the speech-to-text "
            "catalog. Null for a bot that does not transcribe."
        ),
    )
    speech_to_text_model: str | None = Field(
        default=None,
        max_length=255,
        description="Which of that provider's transcription models to use.",
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
    leaves the stored value, null clears it.
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
    speech_to_text_provider: str | None = Field(default=None, max_length=32)
    speech_to_text_model: str | None = Field(default=None, max_length=255)

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
    speech_to_text_provider: str | None = None
    speech_to_text_model: str | None = None
    """Which model transcribes voice notes here, or null for none.

    Read back plainly: a provider id and a model id are choices somebody made,
    not credentials. The key they run on is the organization's own model profile
    and is never named here.
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
