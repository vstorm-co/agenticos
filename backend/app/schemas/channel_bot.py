"""Channel bot, identity, and session schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.urls import ServiceAddress


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


class BotAgent(BaseSchema):
    """An agent that answers on one bot, as the channels listing names it."""

    id: UUID
    name: str
    slug: str
    has_avatar: bool


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
