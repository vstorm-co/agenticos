"""B73 — shop-ai strangler status snapshot."""

from __future__ import annotations

from app.core.config import Settings
from app.services.shop_ai_strangler_status import (
    build_shop_ai_strangler_status,
    multi_agent_shop_proxy_configured,
)


def test_multi_agent_proxy_configured_requires_url_and_key() -> None:
    cfg = Settings(
        MULTI_AGENT_BACKEND_URL="http://multi-agent:8002",
        MULTI_AGENT_INTERNAL_API_KEY="secret",
    )
    assert multi_agent_shop_proxy_configured(cfg) is True
    cfg2 = Settings(MULTI_AGENT_BACKEND_URL="", MULTI_AGENT_INTERNAL_API_KEY="secret")
    assert multi_agent_shop_proxy_configured(cfg2) is False


def test_build_status_includes_native_flags() -> None:
    status = build_shop_ai_strangler_status()
    assert "SHOP_AI_NATIVE_WIDGET_ENABLED" in status.native_flags
    assert status.entitlement_check_enabled is False
