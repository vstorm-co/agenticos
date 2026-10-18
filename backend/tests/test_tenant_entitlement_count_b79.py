"""B79 — entitlement replica count on strangler status."""

from __future__ import annotations

from app.services.shop_ai_route_matrix import d4_readiness_summary


def test_d4_entitlement_replica_ready_when_rows_present() -> None:
    d4 = d4_readiness_summary(entitlement_replica_shop_ai_count=2)
    assert d4["entitlement_replica_shop_ai_count"] == 2
    assert d4["entitlement_replica_ready"] is True
