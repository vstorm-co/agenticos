"""B49 — widget handoff native."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.shop_widget import ShopWidgetChatIn
from app.services.shop_channel_handling import HANDLING_MODE_QUEUED
from app.services.shop_widget_native_handoff import maybe_escalate_widget, try_widget_handoff_chat_turn

pytestmark = pytest.mark.anyio


async def test_maybe_escalate_widget(monkeypatch: pytest.MonkeyPatch) -> None:
    db = AsyncMock()
    conv_id = uuid4()
    row = MagicMock(handling_mode="ai")
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.handling_repo.get_or_create_ai",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.handling_repo.update",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.conversation_repo.get_conversation_by_id",
        AsyncMock(return_value=MagicMock(title="widget|session")),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.notify_widget_live_agent_queued",
        AsyncMock(),
    )
    reply = await maybe_escalate_widget(
        db,
        organization_id=uuid4(),
        tenant_id=uuid4(),
        conversation_id=conv_id,
        message="gặp nhân viên",
    )
    assert reply is not None
    assert "CSKH" in reply


async def test_handoff_turn_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id = uuid4()
    tenant_id = uuid4()
    session_id = uuid4()
    conv = MagicMock(id=uuid4())
    db = AsyncMock()
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.shop_native_widget_handoff_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.widget_conv_repo.ensure_widget_conversation",
        AsyncMock(return_value=conv),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.get_handling_mode",
        AsyncMock(return_value="ai"),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.maybe_escalate_widget",
        AsyncMock(return_value="Chuyển CSKH"),
    )
    monkeypatch.setattr(
        "app.services.shop_widget_native_handoff.persist_widget_exchange",
        AsyncMock(),
    )
    out = await try_widget_handoff_chat_turn(
        db,
        organization_id=org_id,
        tenant_id=tenant_id,
        data=ShopWidgetChatIn(message="gặp nhân viên", session_id=session_id),
    )
    assert out is not None
    assert out.handling_mode == HANDLING_MODE_QUEUED
    assert out.reply == "Chuyển CSKH"
