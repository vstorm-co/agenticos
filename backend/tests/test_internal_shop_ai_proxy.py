"""Shop MCP strangler proxy routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from starlette.responses import Response

pytestmark = pytest.mark.anyio


async def test_proxy_shop_mcp_forwards(client, api_key_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_proxy(**kwargs):
        captured.update(kwargs)
        return Response(content=b'{"items":[]}', media_type="application/json")

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_mcp_reads_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.proxy_shop_ai_request",
        fake_proxy,
    )

    headers = {
        **api_key_headers,
        "X-Tenant-Id": str(tenant_id),
    }
    resp = await client.get(
        "/api/v1/internal/shop-ai/mcp/catalog",
        headers=headers,
    )
    assert resp.status_code == 200
    assert captured["subpath"] == "mcp/catalog"
    assert captured["tenant_id"] == tenant_id


async def test_proxy_shop_mcp_requires_tenant(client, api_key_headers) -> None:
    resp = await client.get(
        "/api/v1/internal/shop-ai/mcp/catalog",
        headers=api_key_headers,
    )
    assert resp.status_code == 400


async def test_proxy_shop_mcp_org_mismatch(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = uuid4()
    other_tenant = uuid4()
    org_id = uuid4()

    ctx = MagicMock()
    ctx.minerp_tenant_id = other_tenant

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.tenant_context_for_organization",
        AsyncMock(return_value=ctx),
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_native_mcp_reads_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.list_shop_mcp_connections",
        AsyncMock(side_effect=AssertionError("should not list when org mismatch")),
    )

    headers = {
        **api_key_headers,
        "X-Tenant-Id": str(tenant_id),
        "X-Organization-Id": str(org_id),
    }
    resp = await client.get(
        "/api/v1/internal/shop-ai/mcp/connections",
        headers=headers,
    )
    assert resp.status_code == 400
