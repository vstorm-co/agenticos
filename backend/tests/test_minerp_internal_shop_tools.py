"""Native minerp_internal_shop tools (storefront BFF)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agents.deps import AgentDeps
from app.integrations.minerp_shop import tools as shop_tools
from app.integrations.minerp_shop.toolset import build_minerp_internal_shop_toolset

pytestmark = pytest.mark.anyio


def _ctx(*, tenant_id):
    deps = AgentDeps(
        organization_id=uuid4(),
        minerp_tenant_id=tenant_id,
    )
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


async def test_search_shop_products_uses_minerp_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    captured: dict[str, str] = {}

    async def fake_search(*, tenant_id: str, query: str, limit: int = 5):
        captured["tenant_id"] = tenant_id
        captured["query"] = query
        return {"items": [{"id": "1", "name": "Bánh mì"}]}

    monkeypatch.setattr(
        "app.integrations.minerp_shop.tools.shop_client.search_shop_products",
        fake_search,
    )
    result = await shop_tools.search_shop_products(_ctx(tenant_id=tenant_id), "banh mi", 3)
    assert captured["tenant_id"] == str(tenant_id)
    assert "Bánh mì" in result


async def test_search_missing_tenant_context() -> None:
    result = await shop_tools.search_shop_products(_ctx(tenant_id=None), "x", 5)
    assert "tenant context missing" in result.lower()


def test_build_internal_shop_toolset_prefix() -> None:
    toolset = build_minerp_internal_shop_toolset(
        connection_name="shop-catalog",
        allowed_tools=["search_shop_products"],
    )
    assert toolset is not None
