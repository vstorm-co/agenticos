"""D3 slice 6 — merchant assistant chat native."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.shop_merchant_chat_native import try_native_merchant_chat

pytestmark = pytest.mark.anyio


async def test_merchant_chat_bestseller_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native.shop_native_merchant_chat_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native._bff_ready",
        lambda _tid: True,
    )
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native.shop_client.get_shop_bestsellers",
        AsyncMock(return_value={"items": [{"name": "A", "id": str(uuid4())}], "days": 30}),
    )
    reply = await try_native_merchant_chat(
        tenant_id=tenant_id,
        message="món nào bán chạy",
    )
    assert reply is not None
    assert "Top bán chạy" in reply or "order nhiều nhất" in reply


async def test_merchant_chat_strangler_when_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native.shop_native_merchant_chat_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native._bff_ready",
        lambda _tid: True,
    )
    monkeypatch.setattr(
        "app.services.shop_merchant_chat_native.shop_native_merchant_chat_strangler_fallback",
        lambda: True,
    )
    reply = await try_native_merchant_chat(
        tenant_id=tenant_id,
        message="phân tích chiến dịch ads tuần này chi tiết",
    )
    assert reply is None


async def test_merchant_chat_route_native(client, api_key_headers, monkeypatch) -> None:
    tenant_id = uuid4()
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.try_native_merchant_chat",
        AsyncMock(return_value="ok merchant"),
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.post(
        "/api/v1/internal/shop-ai/merchant-assistant/chat",
        headers=headers,
        json={"message": "tra don"},
    )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "ok merchant"
