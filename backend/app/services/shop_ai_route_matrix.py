"""D3 shop-ai route parity matrix (B77) — native vs proxy vs hybrid."""

from __future__ import annotations

from typing import Literal

from app.core.config import Settings, settings
from app.schemas.shop_ai_strangler_status import ShopAiRouteParityRead
from app.services.shop_ai_strangler_status import multi_agent_shop_proxy_configured
from app.services.shop_ai_mcp_native import (
    shop_native_mcp_reads_enabled,
    shop_native_merchant_mcp_reads_enabled,
)
from app.services.shop_ai_llm_strangler import (
    shop_merchant_llm_strangler_enabled,
    shop_widget_llm_strangler_enabled,
)
from app.services.shop_widget_chat_native import widget_poll_use_strangler

RouteMode = Literal["native", "proxy", "hybrid", "catch_all_proxy"]


def _mode_native_or_proxy(flag: bool) -> RouteMode:
    return "native" if flag else "proxy"


def _mode_hybrid_native_first(flag: bool) -> RouteMode:
    return "hybrid" if flag else "proxy"


def build_shop_ai_route_matrix(cfg: Settings | None = None) -> list[ShopAiRouteParityRead]:
    cfg = cfg or settings
    proxy_ok = multi_agent_shop_proxy_configured(cfg)

    def m(method: str, path: str, mode: RouteMode, note: str) -> ShopAiRouteParityRead:
        effective = mode
        if mode in ("proxy", "hybrid", "catch_all_proxy") and not proxy_ok:
            note = f"{note}; multi-agent proxy not configured"
        return ShopAiRouteParityRead(
            method=method,
            path=path,
            mode=effective,
            note=note,
        )

    rows: list[ShopAiRouteParityRead] = [
        m("GET", "/strangler-status", "native", "Ops flags + matrix (B73/B77)"),
        m(
            "GET",
            "/mcp/catalog",
            _mode_native_or_proxy(shop_native_mcp_reads_enabled()),
            "Org MCP catalog",
        ),
        m(
            "GET",
            "/mcp/connections",
            _mode_native_or_proxy(shop_native_mcp_reads_enabled()),
            "Org MCP connections list",
        ),
        m(
            "POST",
            "/mcp/connections",
            "hybrid" if cfg.SHOP_AI_NATIVE_MCP_WRITES_ENABLED else "proxy",
            "Create connection native when flag on",
        ),
        m(
            "POST",
            "/widget/chat",
            "hybrid" if cfg.SHOP_AI_NATIVE_WIDGET_ENABLED else "proxy",
            "Deterministic/FAQ/handoff native; LLM via strangler",
        ),
        m(
            "GET",
            "/widget/poll",
            "native" if cfg.SHOP_AI_NATIVE_WIDGET_POLL_NATIVE and not widget_poll_use_strangler() else "hybrid",
            "Poll queue on Agentra when native",
        ),
        m(
            "POST",
            "/merchant-assistant/chat",
            "hybrid" if cfg.SHOP_AI_NATIVE_MERCHANT_CHAT_ENABLED else "proxy",
            "Deterministic native; LLM strangler when enabled",
        ),
        m("POST", "/llm-generate", "native" if cfg.SHOP_AI_NATIVE_LLM_GENERATE_ENABLED else "proxy", "One-shot LLM"),
        m("GET", "/catalog-sync", "native", "B63 catalog settings"),
        m("POST", "/catalog-sync/run", "native", "Manual catalog run"),
        m(
            "GET",
            "/channel/sessions",
            _mode_native_or_proxy(cfg.SHOP_AI_NATIVE_CHANNEL_SESSIONS_ENABLED),
            "Channel inbox",
        ),
        m(
            "GET",
            "/channel-bots",
            _mode_native_or_proxy(cfg.SHOP_AI_NATIVE_CHANNEL_BOTS_ENABLED),
            "Shop CSKH bots CRUD",
        ),
        m(
            "POST",
            "/zalo-oauth/start",
            _mode_native_or_proxy(cfg.SHOP_AI_NATIVE_ZALO_OAUTH_ENABLED),
            "Studio Zalo connect",
        ),
        m("GET", "/knowledge-bases", "native", "Tenant KB list on Agentra org"),
        m("GET", "/background-jobs", "native" if cfg.SHOP_AGENT_BACKGROUND_JOB_ENABLED else "proxy", "B62 jobs"),
        m("GET", "/live-agent/inbox-summary", "native", "Widget + channel queue counts"),
        m(
            "*",
            "/{subpath}",
            "catch_all_proxy",
            "Unlisted Studio paths forward to multi-agent",
        ),
    ]

    extra_notes: dict[str, str] = {}
    if shop_widget_llm_strangler_enabled():
        extra_notes["/widget/chat"] = "LLM leg → multi-agent when native misses"
    if shop_merchant_llm_strangler_enabled():
        extra_notes["/merchant-assistant/chat"] = "LLM leg → multi-agent"
    if not extra_notes:
        return rows
    out: list[ShopAiRouteParityRead] = []
    for row in rows:
        suffix = extra_notes.get(row.path)
        if suffix:
            out.append(
                ShopAiRouteParityRead(
                    method=row.method,
                    path=row.path,
                    mode=row.mode,
                    note=f"{row.note}; {suffix}",
                )
            )
        else:
            out.append(row)
    return out


def d4_readiness_summary(
    cfg: Settings | None = None,
    *,
    entitlement_replica_shop_ai_count: int = 0,
) -> dict[str, bool | str | int]:
    """D4 gate hints — not a hard blocker, for cutover checklist."""
    cfg = cfg or settings
    proxy_ok = multi_agent_shop_proxy_configured(cfg)
    matrix = build_shop_ai_route_matrix(cfg)
    catch_all = next((r for r in matrix if r.path == "/{subpath}"), None)
    entitlement_check = bool(cfg.SHOP_AI_NATIVE_ENTITLEMENT_CHECK_ENABLED)
    return {
        "multi_agent_proxy_configured": proxy_ok,
        "can_attempt_empty_multi_agent_url": not proxy_ok
        or all(r.mode == "native" for r in matrix if r.mode != "catch_all_proxy"),
        "catch_all_still_active": catch_all is not None and catch_all.mode == "catch_all_proxy",
        "entitlement_check_requires_cdc": entitlement_check,
        "entitlement_replica_shop_ai_count": entitlement_replica_shop_ai_count,
        "entitlement_replica_ready": (not entitlement_check)
        or entitlement_replica_shop_ai_count > 0,
        "prefect_shop_beats": bool(
            cfg.SHOP_AI_CATALOG_SYNC_NIGHTLY_ENABLED
            or cfg.SHOP_AGENT_BACKGROUND_DIGEST_ENABLED
            or cfg.SHOP_AI_ZALO_OAUTH_REFRESH_ENABLED
        ),
    }
