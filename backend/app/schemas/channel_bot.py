"""Channel bot, identity, and session schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class AccessPolicy(BaseSchema):
    """Bot access control policy."""

    mode: Literal["open", "whitelist", "jwt_linked", "group_only"] = "open"
    whitelist: list[str] = []
    allowed_groups: list[str] = []
    require_link: bool = False
    rate_limit_rpm: int = 10
    denied_message: str = "You are not authorised to use this bot."


class ChannelBotCreate(BaseSchema):
    """Schema for creating a channel bot."""

    platform: str = Field("telegram", max_length=20)
    name: str = Field(..., max_length=255)
    token: str = Field(..., min_length=10, max_length=500)
    webhook_mode: bool = False
    webhook_url: str | None = None
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


class ChannelBotUpdate(BaseSchema):
    """Schema for updating a channel bot (all fields optional).

    The Slack credentials distinguish omission from an explicit null: omitted
    leaves the stored value, null clears it.
    """

    name: str | None = Field(default=None, max_length=255)
    token: str | None = Field(default=None, min_length=10, max_length=500)
    webhook_mode: bool | None = None
    webhook_url: str | None = None
    access_policy: AccessPolicy | None = None
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
    access_policy: AccessPolicy
    # Booleans, never the values: the panel needs "is this configured", and a
    # response is the way a sealed credential usually escapes.
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
