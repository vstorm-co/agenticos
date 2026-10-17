"""D3 native Shop AI reads via storefront BFF."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from starlette.responses import Response

from app.services.multi_agent_shop_proxy import proxy_shop_ai_request
from app.services.shop_ai_bff_native import is_bff_native_read_subpath, maybe_proxy_bff_native_read

pytestmark = pytest.mark.anyio


def test_is_bff_native_read_subpath() -> None:
    assert is_bff_native_read_subpath("products", "GET") is True
    assert is_bff_native_read_subpath("products/sku-1", "GET") is True
    assert is_bff_native_read_subpath("catalog/items", "GET") is True
    assert is_bff_native_read_subpath("mcp/catalog", "GET") is False
    assert is_bff_native_read_subpath("products", "POST") is False


async def test_maybe_proxy_bff_native_read_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    request = MagicMock()
    request.method = "GET"
    request.url.query = "q=ao"
    request.headers = {"accept": "application/json"}

    monkeypatch.setattr(
        "app.services.shop_ai_bff_native.shop_client.shop_cskh_bff_configured",
        lambda *, tenant_id: True,
    )
    monkeypatch.setattr(
        "app.services.shop_ai_bff_native.shop_client.shop_cskh_bff_base_url",
        lambda *, tenant_id: "http://storefront.test",
    )
    monkeypatch.setattr(
        "app.services.shop_ai_bff_native.shop_client.shop_cskh_bff_request_headers",
        lambda *, tenant_id: {"X-Tenant-Id": tenant_id, "X-API-Key": "k"},
    )

    mock_response = httpx.Response(200, json={"items": [], "total": 0})

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers=None):
            assert "internal/shop-ai/products" in url
            assert "q=ao" in url
            return mock_response

    monkeypatch.setattr(
        "app.services.shop_ai_bff_native.httpx.AsyncClient",
        lambda **kwargs: FakeClient(),
    )

    resp = await maybe_proxy_bff_native_read(
        request=request, subpath="products", tenant_id=tenant_id
    )
    assert resp is not None
    assert resp.status_code == 200


async def test_proxy_shop_ai_uses_bff_before_multi_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    request = MagicMock()
    request.method = "GET"
    request.url.query = ""
    request.headers = {}

    bff = Response(content=b'{"ok":true}', media_type="application/json")

    monkeypatch.setattr(
        "app.services.shop_ai_bff_native.maybe_proxy_bff_native_read",
        AsyncMock(return_value=bff),
    )
    ma = AsyncMock()
    monkeypatch.setattr(
        "app.services.multi_agent_shop_proxy._proxy_shop_ai_buffered",
        ma,
    )

    out = await proxy_shop_ai_request(request=request, subpath="bestsellers", tenant_id=tenant_id)
    assert out is bff
    ma.assert_not_called()
