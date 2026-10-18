"""B86 — D4 blocker list."""

from __future__ import annotations

from unittest.mock import patch

from app.services.shop_d4_readiness import compute_d4_blockers


def test_d4_blockers_include_catch_all_when_enabled() -> None:
    with patch(
        "app.services.shop_d4_readiness.multi_agent_shop_proxy_configured",
        return_value=True,
    ):
        blockers = compute_d4_blockers()
    assert "catch_all_proxy" in blockers
    assert "merchant_mcp_ads_calendar_email_proxy" in blockers
