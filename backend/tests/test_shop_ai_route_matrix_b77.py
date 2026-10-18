"""B77 — shop-ai route parity matrix."""

from __future__ import annotations

from app.services.shop_ai_route_matrix import build_shop_ai_route_matrix, d4_readiness_summary


def test_route_matrix_includes_catch_all() -> None:
    rows = build_shop_ai_route_matrix()
    paths = {r.path for r in rows}
    assert "/{subpath}" in paths
    assert any(r.path == "/strangler-status" and r.mode == "native" for r in rows)


def test_d4_readiness_has_proxy_flag() -> None:
    summary = d4_readiness_summary()
    assert "multi_agent_proxy_configured" in summary
    assert "catch_all_still_active" in summary
