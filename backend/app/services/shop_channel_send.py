"""Outbound shop channel messages (Zalo OA token + adapter)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.channel_bot import ChannelBot
from app.services.channel_bot import unseal_bot_token
from app.services.channels import get_adapter
from app.services.channels.base import IncomingMessage, OutgoingMessage
from app.services.shop_zalo_oauth_flow import ensure_shop_zalo_access_token

logger = logging.getLogger(__name__)


async def send_shop_channel_text(
    db: AsyncSession,
    *,
    bot: ChannelBot,
    incoming: IncomingMessage,
    text: str,
) -> None:
    try:
        adapter = get_adapter(bot.platform)
    except KeyError:
        logger.warning(
            "No channel adapter for platform=%s; message not delivered",
            bot.platform,
        )
        return
    try:
        if bot.platform == "zalo":
            token = await ensure_shop_zalo_access_token(db, bot)
        else:
            token = unseal_bot_token(bot)
        out = OutgoingMessage(platform_chat_id=incoming.platform_chat_id, text=text)
        await adapter.send_message(token, out)
    except Exception:
        logger.exception(
            "Failed to deliver shop channel reply platform=%s bot_id=%s",
            bot.platform,
            bot.id,
        )
