"""Shop CSKH channel bots — Studio parity with multi-agent internal shop-ai."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema
from app.schemas.channel_bot import AccessPolicy

BotKindLiteral = Literal["platform", "shop_cskh"]
AgentModeLiteral = Literal["single", "multi"]


class ShopChannelBotCreate(BaseSchema):
    """Create a shop CSKH bot (Zalo / Messenger)."""

    platform: str = Field("zalo", max_length=20)
    name: str = Field(..., max_length=255)
    token: str = Field(..., min_length=10, max_length=500)
    webhook_mode: bool = False
    webhook_url: str | None = None
    webhook_secret: str | None = Field(default=None, max_length=255)
    access_policy: AccessPolicy = Field(default_factory=AccessPolicy)
    ai_model_override: str | None = None
    system_prompt_override: str | None = None
    agent_mode: AgentModeLiteral = "single"
    enabled_specialists: list[str] | None = None
    tenant_id: UUID | None = Field(
        default=None, description="Shop tenant (required when bot_kind=shop_cskh)"
    )
    bot_kind: BotKindLiteral = Field(default="shop_cskh")
    default_kb_id: UUID | None = Field(
        default=None, description="Default FAQ knowledge base for shop CSKH"
    )

    @model_validator(mode="after")
    def validate_shop_cskh(self) -> Self:
        if self.bot_kind == "shop_cskh":
            if self.tenant_id is None:
                raise ValueError("tenant_id is required when bot_kind is shop_cskh")
            if self.platform not in ("zalo", "messenger"):
                raise ValueError("shop_cskh bots must use platform=zalo or messenger")
        return self


class ShopChannelBotUpdate(BaseSchema):
    """Patch shop CSKH bot fields."""

    name: str | None = Field(default=None, max_length=255)
    token: str | None = Field(default=None, min_length=10, max_length=500)
    webhook_mode: bool | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = Field(default=None, max_length=255)
    access_policy: AccessPolicy | None = None
    ai_model_override: str | None = None
    system_prompt_override: str | None = None
    agent_mode: AgentModeLiteral | None = None
    enabled_specialists: list[str] | None = None
    is_active: bool | None = None
    default_kb_id: UUID | None = None


class ShopChannelBotRead(BaseSchema):
    """Shop channel bot row (no token ciphertext)."""

    id: UUID
    platform: str
    name: str
    is_active: bool
    webhook_mode: bool
    webhook_url: str | None
    access_policy: AccessPolicy
    ai_model_override: str | None = None
    system_prompt_override: str | None = None
    agent_mode: AgentModeLiteral = "single"
    enabled_specialists: list[str] | None = None
    tenant_id: UUID | None = None
    bot_kind: BotKindLiteral = "shop_cskh"
    default_kb_id: UUID | None = None
    webhook_register_url: str | None = Field(
        default=None,
        description="Public webhook URL to paste in Zalo / Meta developer console",
    )
    auth_method: Literal["token_paste", "oauth"] = "token_paste"
    zalo_oa_id: str | None = None
    oauth_connected: bool = False
    token_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class ShopChannelBotList(BaseSchema):
    items: list[ShopChannelBotRead]
    total: int
