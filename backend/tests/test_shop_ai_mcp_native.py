"""D3 slice 2 — native Shop MCP catalog/connections."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.integrations.minerp_shop.constants import MINERP_INTERNAL_SHOP_CATALOG_KEY
from app.services.shop_ai_mcp_native import list_shop_mcp_catalog

pytestmark = pytest.mark.anyio


async def test_list_shop_mcp_catalog_includes_internal_shop() -> None:
    listing = await list_shop_mcp_catalog()
    assert listing.total >= 1
    keys = {item.id for item in listing.items}
    assert MINERP_INTERNAL_SHOP_CATALOG_KEY in keys
    shop = next(i for i in listing.items if i.id == MINERP_INTERNAL_SHOP_CATALOG_KEY)
    assert shop.transport == "internal"
    assert len(shop.tools) == 4


async def test_shop_mcp_catalog_route_native(client, api_key_headers, monkeypatch) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_mcp_reads_enabled",
        lambda: True,
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.get("/api/v1/internal/shop-ai/mcp/catalog", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(i["id"] == MINERP_INTERNAL_SHOP_CATALOG_KEY for i in body["items"])


async def test_shop_mcp_create_route_strangler_when_oauth(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.responses import Response

    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.create_shop_mcp_connection",
        AsyncMock(return_value=None),
    )

    async def fake_proxy(**kwargs):
        return Response(
            content=b'{"id":"00000000-0000-4000-8000-000000000001","connector_id":"stripe","name":"x","perm":"readonly","is_active":true,"has_credentials":false,"oauth_connected":false}',
            media_type="application/json",
            status_code=201,
        )

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.proxy_shop_ai_request",
        fake_proxy,
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.post(
        "/api/v1/internal/shop-ai/mcp/connections",
        headers=headers,
        json={
            "connector_id": "stripe",
            "name": "Stripe",
            "perm": "readonly",
            "oauth_client_id": "cid",
        },
    )
    assert resp.status_code == 201


async def test_merchant_mcp_catalog_route_native(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_merchant_mcp_reads_enabled",
        lambda: True,
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.get(
        "/api/v1/internal/shop-ai/merchant/mcp/catalog",
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(i["id"] == MINERP_INTERNAL_SHOP_CATALOG_KEY for i in body["items"])


async def test_merchant_mcp_connections_route_native(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    from app.schemas.shop_ai_mcp import ShopMcpConnectionList

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_merchant_mcp_reads_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.list_merchant_mcp_connections",
        AsyncMock(return_value=ShopMcpConnectionList(items=[], total=0)),
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.get(
        "/api/v1/internal/shop-ai/merchant/mcp/connections",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


async def test_shop_mcp_connections_route_native(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    from app.schemas.shop_ai_mcp import ShopMcpConnectionList

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_mcp_reads_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.list_shop_mcp_connections",
        AsyncMock(return_value=ShopMcpConnectionList(items=[], total=0)),
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.get("/api/v1/internal/shop-ai/mcp/connections", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}
