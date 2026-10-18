"""B68 — shop channel inbound handoff."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.db.models.channel_bot import BOT_KIND_SHOP_CSKH
from app.services.channels.base import IncomingMessage
from app.services.shop_channel_handling import HANDLING_MODE_AI, HANDLING_MODE_QUEUED
from app.core.config import settings
from app.services.shop_channel_inbound import handle_shop_channel_inbound

pytestmark = pytest.mark.anyio


async def test_handoff_to_queued_on_human_agent_phrase() -> None:
    db = MagicMock()
    tenant_id = uuid4()
    conv_id = uuid4()
    bot = MagicMock()
    bot.bot_kind = BOT_KIND_SHOP_CSKH
    bot.minerp_tenant_id = tenant_id
    bot.default_kb_id = None
    bot.platform = "zalo"
    bot.id = uuid4()
    bot.organization_id = uuid4()

    session = MagicMock()
    session.id = uuid4()
    session.conversation_id = conv_id
    session.handling_mode = HANDLING_MODE_AI

    incoming = IncomingMessage(
        platform="zalo",
        bot_id=str(bot.id),
        platform_user_id="u1",
        platform_chat_id="u1",
        chat_type="private",
        text="cho gap nhan vien",
    )

    with (
        patch.object(settings, "SHOP_AI_NATIVE_CHANNEL_INBOUND_ENABLED", True),
        patch(
            "app.services.shop_channel_inbound.conversation_repo.create_message",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_inbound.channel_session_repo.update",
            new=AsyncMock(return_value=session),
        ) as upd,
        patch(
            "app.services.shop_channel_inbound.channel_session_repo.touch",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_inbound.send_shop_channel_text",
            new=AsyncMock(),
        ),
        patch(
            "app.services.shop_channel_inbound.channel_identity_repo.get_by_id",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.shop_channel_inbound.notify_channel_live_agent_queued",
            new=AsyncMock(),
        ),
    ):
        handled = await handle_shop_channel_inbound(
            db,
            bot=bot,
            session=session,
            incoming=incoming,
        )

    assert handled is True
    upd.assert_awaited_once()
    assert upd.await_args.kwargs["update_data"]["handling_mode"] == HANDLING_MODE_QUEUED
