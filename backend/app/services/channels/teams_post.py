"""Posting into a Teams conversation without being asked (#1985).

A trigger's answer goes to a team channel or group chat its bot is in. The
conversation's record says where it lives; the bot's row says how to sign in.
Nothing about this is an answer to an activity, so nothing here has an activity
to read either.
"""

import logging
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import channel_bot_repo, teams_conversation_repo
from app.services.channel_bot import unseal_bot_token
from app.services.channels.base import OutgoingMessage
from app.services.channels.exceptions import ChannelNotConfigured
from app.services.channels.teams import ConversationRef, teams_adapter

logger = logging.getLogger(__name__)


async def post_to_teams(db: AsyncSession, conversation_id: UUID, text: str) -> bool:
    """Post `text` as a new message in a Teams conversation. True if it was sent.

    A conversation or bot that is gone, a bot that was switched off, and a
    Connector that refuses all answer False with a log line: the fire that asked
    for the post has already happened and been recorded, and its run log is the
    record of what it said.
    """
    row = await teams_conversation_repo.get_by_id(db, conversation_id)
    if row is None:
        return False
    bots = await channel_bot_repo.get_by_ids(db, {row.bot_id})
    bot = bots.get(row.bot_id)
    if bot is None or not bot.is_active:
        return False
    adapter = teams_adapter()
    adapter.know(
        ConversationRef(
            conversation_id=row.conversation_id,
            service_url=row.service_url,
            conversation_type=row.conversation_type,
            tenant_id=row.tenant_id,
            name=row.name,
        )
    )
    try:
        await adapter.send_message(
            unseal_bot_token(bot), OutgoingMessage(platform_chat_id=row.key, text=text)
        )
    except httpx.HTTPError, ChannelNotConfigured, ValueError:
        logger.warning(
            "teams_post_failed",
            extra={"teams_conversation_id": str(conversation_id), "bot_id": str(bot.id)},
            exc_info=True,
        )
        return False
    return True
