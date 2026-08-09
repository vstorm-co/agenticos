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
    """When this bot says what a turn cost, and when it only records it.

    Separate from `AccessPolicy` because they answer different questions: that one
    decides who may talk to the bot, this one decides how talkative the bot is
    about spending. One object holding both would put them in the same form and in
    the same JSON value, and the next person narrowing access would be editing the
    setting somebody else tuned for noise.
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
    usage_reporting: UsageReporting = Field(default_factory=UsageReporting)
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
    usage_reporting: UsageReporting | None = None
    is_active: bool | None = None
    slack_signing_secret: str | None = Field(default=None, min_length=8, max_length=255)
    slack_app_token: str | None = Field(default=None, min_length=8, max_length=500)


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
    usage_reporting: UsageReporting = Field(default_factory=UsageReporting)
    # Booleans, never the values: the panel needs "is this configured", and a
    # response is the way a sealed credential usually escapes.
    has_webhook_secret: bool = False
    has_slack_signing_secret: bool = False
    has_slack_app_token: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class ChannelBotList(BaseSchema):
    """Paginated list of channel bots."""

    items: list[ChannelBotRead]
    total: int


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
