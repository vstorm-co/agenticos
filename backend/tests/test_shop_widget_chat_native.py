"""D3 slice 3 — native Shop widget chat."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.shop_widget import ShopWidgetChatIn
from app.services.shop_widget_chat_native import try_native_widget_chat

pytestmark = pytest.mark.anyio


async def test_native_widget_greeting(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native._bff_ready",
        lambda _tid: True,
    )
    out = await try_native_widget_chat(
        tenant_id=tenant_id,
        data=ShopWidgetChatIn(message="xin chào", session_id=session_id),
    )
    assert out is not None
    assert "Chào bạn" in out.reply
    assert out.session_id == session_id
    assert out.handling_mode == "ai"


async def test_native_widget_faq_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native._bff_ready",
        lambda _tid: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_strangler_fallback",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.try_widget_faq_rag_reply",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_handoff_enabled",
        lambda: False,
    )
    out = await try_native_widget_chat(
        tenant_id=tenant_id,
        data=ShopWidgetChatIn(
            message="chính sách giao hàng như thế nào?",
            session_id=session_id,
        ),
        db=AsyncMock(),
    )
    assert out is None


async def test_native_widget_faq_rag_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native._bff_ready",
        lambda _tid: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.try_widget_faq_rag_reply",
        AsyncMock(return_value="Dạ, theo thông tin shop:\n\nShip 2-3 ngày."),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_handoff_enabled",
        lambda: False,
    )
    out = await try_native_widget_chat(
        tenant_id=tenant_id,
        data=ShopWidgetChatIn(
            message="chính sách giao hàng?",
            session_id=session_id,
        ),
        db=AsyncMock(),
    )
    assert out is not None
    assert "Ship 2-3 ngày" in out.reply


async def test_widget_chat_route_native(client, api_key_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    from app.schemas.shop_widget import ShopWidgetChatOut

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.try_native_widget_chat",
        AsyncMock(
            return_value=ShopWidgetChatOut(
                reply="ok",
                session_id=session_id,
                actions=[],
                handling_mode="ai",
            )
        ),
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.post(
        "/api/v1/internal/shop-ai/widget/chat",
        headers=headers,
        json={"message": "hi", "session_id": str(session_id)},
    )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "ok"


async def test_widget_chat_route_strangler(
    client, api_key_headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.responses import Response

    tenant_id = uuid4()
    session_id = uuid4()
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.try_native_widget_chat",
        AsyncMock(return_value=None),
    )

    async def fake_proxy(**kwargs):
        return Response(
            content=b'{"reply":"from-ma","session_id":"'
            + str(session_id).encode()
            + b'","actions":[],"handling_mode":"ai"}',
            media_type="application/json",
        )

    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.strangler_widget_chat",
        fake_proxy,
    )
    monkeypatch.setattr(
        "app.api.routes.v1.internal_shop_ai.shop_widget_llm_strangler_enabled",
        lambda: True,
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.post(
        "/api/v1/internal/shop-ai/widget/chat",
        headers=headers,
        json={"message": "complex", "session_id": str(session_id)},
    )
    assert resp.status_code == 200
    assert resp.json()["reply"] == "from-ma"


async def test_widget_poll_route_native(client, api_key_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    session_id = uuid4()
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.settings.SHOP_AI_NATIVE_WIDGET_POLL_NATIVE",
        True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_chat_native.shop_native_widget_handoff_enabled",
        lambda: False,
    )
    headers = {**api_key_headers, "X-Tenant-Id": str(tenant_id)}
    resp = await client.get(
        "/api/v1/internal/shop-ai/widget/poll",
        headers=headers,
        params={"session_id": str(session_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == str(session_id)
    assert body["handling_mode"] == "ai"
    assert body["items"] == []
