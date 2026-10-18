"""Ops read model for D3 shop-ai native vs proxy flags (B73)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.base import BaseSchema


class ShopAiRouteParityRead(BaseSchema):
    method: str
    path: str
    mode: str = Field(description="native | proxy | hybrid | catch_all_proxy")
    note: str = ""


class ShopAiStranglerStatusRead(BaseSchema):
    multi_agent_proxy_configured: bool = Field(
        description="MULTI_AGENT_BACKEND_URL and internal API key are set"
    )
    entitlement_check_enabled: bool
    native_flags: dict[str, bool] = Field(
        description="SHOP_AI_NATIVE_* toggles from Agentra settings"
    )
    routes: list[ShopAiRouteParityRead] = Field(default_factory=list)
    d4_readiness: dict[str, Any] = Field(default_factory=dict)
    entitlement_replica_shop_ai_count: int = Field(
        0,
        description="Active shop_ai rows in IAM CDC replica table (B79)",
    )
