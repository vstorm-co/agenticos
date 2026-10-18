"""B86 — explicit D4 decommission blockers for shop-ai strangler."""

from __future__ import annotations

from app.core.config import Settings, settings
from app.services.shop_ai_strangler_status import multi_agent_shop_proxy_configured
from app.services.shop_ai_llm_strangler import (
    shop_merchant_llm_strangler_enabled,
    shop_widget_llm_strangler_enabled,
)
from app.services.shop_channel_agent_native import shop_channel_agent_native_enabled
from app.services.shop_channel_agent_strangler import shop_channel_agent_strangler_enabled
from app.services.shop_chat_llm_native import (
    shop_merchant_llm_on_agentra_enabled,
    shop_widget_llm_on_agentra_enabled,
)
from app.services.shop_llm_openai import shop_llm_generate_configured


def compute_d4_blockers(cfg: Settings | None = None) -> list[str]:
    cfg = cfg or settings
    blockers: list[str] = []
    if not multi_agent_shop_proxy_configured(cfg):
        return blockers

    if cfg.SHOP_AI_CATCH_ALL_PROXY_ENABLED:
        blockers.append("catch_all_proxy")

    llm_key = shop_llm_generate_configured()
    if shop_widget_llm_strangler_enabled():
        if not (shop_widget_llm_on_agentra_enabled() and llm_key):
            blockers.append("widget_chat_llm_multi_agent")
    if shop_merchant_llm_strangler_enabled():
        if not (shop_merchant_llm_on_agentra_enabled() and llm_key):
            blockers.append("merchant_chat_llm_multi_agent")

    if shop_channel_agent_strangler_enabled() and not (
        shop_channel_agent_native_enabled() and llm_key
    ):
        blockers.append("channel_agent_multi_agent")

    if not shop_native_mcp_merchant_extensions(cfg):
        blockers.append("merchant_mcp_ads_calendar_email_proxy")

    return blockers


def shop_native_mcp_merchant_extensions(cfg: Settings) -> bool:
    """B84 deferred — merchant non-catalog MCP still on multi-agent."""
    _ = cfg
    return False
