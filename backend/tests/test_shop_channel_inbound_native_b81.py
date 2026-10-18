"""B81 — channel inbound prefers native agent before multi-agent strangler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.channel_bot import BOT_KIND_SHOP_CSKH
from app.core.config import settings
from app.services.channels.base import IncomingMessage
from app.services.shop_channel_handling import HANDLING_MODE_AI
from app.services.shop_channel_inbound import handle_shop_channel_inbound

pytestmark = pytest.mark.anyio


async def test_inbound_uses_native_agent_when_widget_and_llm_miss() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    conv_id = uuid4()
    bot = MagicMock()
    bot.bot_kind = BOT_KIND_SHOP_CSKH
    bot.minerp_tenant_id = tenant_id
    bot.default_kb_id = None
    bot.organization_id = uuid4()

    session = MagicMock()
    session.id = uuid4()
    session.conversation_id = conv_id
    session.handling_mode = HANDLING_MODE_AI

    incoming = IncomingMessage(
        platform="zalo",
        bot_id=str(uuid4()),
        platform_user_id="u1",
        platform_chat_id="u1",
        chat_type="private",
        text="tra don ABC123",
    )

    with (
        patch.object(settings, "SHOP_AI_NATIVE_CHANNEL_INBOUND_ENABLED", True),
        patch(
            "app.services.shop_channel_inbound.conversation_repo.count_messages",
            new=AsyncMock(return_value=1),
        ),
        patch(
            "app.services.shop_channel_inbound.conversation_repo.create_message",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_inbound.channel_session_repo.touch",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_inbound.send_shop_channel_text",
            new=AsyncMock(),
        ) as send,
        patch(
            "app.services.shop_channel_inbound.try_native_widget_chat",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.shop_channel_inbound.try_shop_channel_llm_reply",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.shop_channel_inbound.try_shop_channel_agent_native_reply",
            new=AsyncMock(return_value="Don dang giao"),
        ),
        patch(
            "app.services.shop_channel_inbound.try_shop_channel_agent_strangler_reply",
            new=AsyncMock(return_value="should not call"),
        ),
    ):
        handled = await handle_shop_channel_inbound(
            db,
            bot=bot,
            session=session,
            incoming=incoming,
        )

    assert handled is True
    send.assert_awaited_once()
    assert send.await_args.kwargs["text"] == "Don dang giao"
