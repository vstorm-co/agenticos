"""Collect D3 shop-ai strangler feature flags for ops (B73)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.repositories import tenant_service_entitlement as entitlement_repo
from app.schemas.shop_ai_strangler_status import ShopAiStranglerStatusRead

_NATIVE_FLAG_NAMES: tuple[str, ...] = (
    "SHOP_AI_NATIVE_BFF_READS_ENABLED",
    "SHOP_AI_NATIVE_MCP_READS_ENABLED",
    "SHOP_AI_NATIVE_MCP_WRITES_ENABLED",
    "SHOP_AI_NATIVE_MERCHANT_MCP_READS_ENABLED",
    "SHOP_AI_NATIVE_MERCHANT_CHAT_ENABLED",
    "SHOP_AI_NATIVE_MERCHANT_CHAT_STRANGLER_FALLBACK",
    "SHOP_AI_NATIVE_WIDGET_ENABLED",
    "SHOP_AI_NATIVE_WIDGET_STRANGLER_FALLBACK",
    "SHOP_AI_NATIVE_WIDGET_POLL_NATIVE",
    "SHOP_AI_NATIVE_WIDGET_FAQ_RAG_ENABLED",
    "SHOP_AI_NATIVE_WIDGET_HANDOFF_ENABLED",
    "SHOP_AI_NATIVE_WIDGET_QUEUE_NOTIFY_ENABLED",
    "SHOP_AI_NATIVE_WIDGET_LLM_STRANGLER",
    "SHOP_AI_NATIVE_MERCHANT_LLM_STRANGLER",
    "SHOP_AI_NATIVE_WIDGET_LLM_ON_AGENTRA",
    "SHOP_AI_NATIVE_MERCHANT_LLM_ON_AGENTRA",
    "SHOP_AI_CATCH_ALL_PROXY_ENABLED",
    "SHOP_AGENT_BACKGROUND_JOB_ENABLED",
    "SHOP_AI_NATIVE_LLM_GENERATE_ENABLED",
    "SHOP_AI_NATIVE_ZALO_OAUTH_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_BOTS_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_SESSIONS_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_INBOUND_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_QUEUE_NOTIFY_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_LLM_STRANGLER",
    "SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED",
    "SHOP_AI_CATALOG_SYNC_NIGHTLY_ENABLED",
    "SHOP_AGENT_BACKGROUND_DIGEST_ENABLED",
    "SHOP_AI_ZALO_OAUTH_REFRESH_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_AGENT_ENABLED",
    "SHOP_AI_NATIVE_CHANNEL_AGENT_STRANGLER",
)


def multi_agent_shop_proxy_configured(cfg: Settings | None = None) -> bool:
    cfg = cfg or settings
    base = (cfg.MULTI_AGENT_BACKEND_URL or "").rstrip("/")
    key = (cfg.MULTI_AGENT_INTERNAL_API_KEY or "").strip()
    return bool(base and key)


def build_shop_ai_strangler_status(
    cfg: Settings | None = None,
    *,
    entitlement_replica_shop_ai_count: int = 0,
) -> ShopAiStranglerStatusRead:
    from app.services.shop_ai_route_matrix import (
        build_shop_ai_route_matrix,
        d4_readiness_summary,
    )

    cfg = cfg or settings
    native_flags = {
        name: bool(getattr(cfg, name, False)) for name in _NATIVE_FLAG_NAMES
    }
    return ShopAiStranglerStatusRead(
        multi_agent_proxy_configured=multi_agent_shop_proxy_configured(cfg),
        entitlement_check_enabled=bool(cfg.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED),
        native_flags=native_flags,
        routes=build_shop_ai_route_matrix(cfg),
        d4_readiness=d4_readiness_summary(
            cfg,
            entitlement_replica_shop_ai_count=entitlement_replica_shop_ai_count,
        ),
        entitlement_replica_shop_ai_count=entitlement_replica_shop_ai_count,
    )


async def build_shop_ai_strangler_status_for_db(
    db: AsyncSession,
    cfg: Settings | None = None,
) -> ShopAiStranglerStatusRead:
    """Include IAM replica counts from DB (B79)."""
    count = await entitlement_repo.count_active_shop_ai_entitlements(db)
    return build_shop_ai_strangler_status(
        cfg,
        entitlement_replica_shop_ai_count=count,
    )
