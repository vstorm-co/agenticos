"""Shop CSKH channel inbound (Zalo/Messenger) — live agent + native widget parity AI."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.channel_bot import BOT_KIND_SHOP_CSKH, ChannelBot
from app.repositories import channel_identity_repo, channel_session_repo, conversation_repo
from app.schemas.shop_widget import ShopWidgetChatIn
from app.services.channels.base import IncomingMessage
from app.services.shop_channel_handling import (
    HANDLING_MODE_AI,
    HANDLING_MODE_HUMAN,
    HANDLING_MODE_QUEUED,
    append_live_agent_escalate_hint,
    handoff_reply_for_platform,
    wants_human_agent,
)
from app.services.shop_channel_send import send_shop_channel_text
from app.services.shop_widget_queue_notify import notify_channel_live_agent_queued
from app.services.shop_channel_agent_native import try_shop_channel_agent_native_reply
from app.services.shop_channel_agent_strangler import try_shop_channel_agent_strangler_reply
from app.services.shop_channel_llm_strangler import try_shop_channel_llm_reply
from app.services.shop_widget_chat_native import try_native_widget_chat

logger = logging.getLogger(__name__)

_CHANNEL_LLM_FALLBACK_VI = (
    "Mình chưa hiểu rõ câu hỏi. Bạn thử hỏi tên món, shop bán gì, hoặc tra cứu đơn nhé."
)


async def handle_shop_channel_inbound(
    db: AsyncSession,
    *,
    bot: ChannelBot,
    session,
    incoming: IncomingMessage,
) -> bool:
    """Handle shop CSKH channel turn. Return True when the platform router should stop."""
    if bot.bot_kind != BOT_KIND_SHOP_CSKH or bot.minerp_tenant_id is None:
        return False
    if not settings.SHOP_AI_NATIVE_CHANNEL_INBOUND_ENABLED:
        return False
    if session.conversation_id is None:
        logger.warning("Shop channel session %s has no conversation_id", session.id)
        return False

    tenant_id = bot.minerp_tenant_id
    text = (incoming.text or "").strip()
    if not text:
        return True

    mode = getattr(session, "handling_mode", HANDLING_MODE_AI) or HANDLING_MODE_AI

    if mode in (HANDLING_MODE_HUMAN, HANDLING_MODE_QUEUED):
        await conversation_repo.create_message(
            db,
            conversation_id=session.conversation_id,
            role="user",
            content=text,
        )
        await channel_session_repo.touch(db, session)
        return True

    if mode == HANDLING_MODE_AI and wants_human_agent(text):
        await conversation_repo.create_message(
            db,
            conversation_id=session.conversation_id,
            role="user",
            content=text,
        )
        await channel_session_repo.update(
            db,
            db_session=session,
            update_data={"handling_mode": HANDLING_MODE_QUEUED},
        )
        await channel_session_repo.touch(db, session)
        handoff_text = handoff_reply_for_platform(incoming.platform)
        await conversation_repo.create_message(
            db,
            conversation_id=session.conversation_id,
            role="assistant",
            content=handoff_text,
        )
        await send_shop_channel_text(db, bot=bot, incoming=incoming, text=handoff_text)
        customer_label = (incoming.platform_display_name or "").strip() or incoming.platform_chat_id
        identity = await channel_identity_repo.get_by_id(db, session.identity_id)
        if identity is not None:
            display = (identity.platform_display_name or "").strip()
            if display and display != identity.platform_user_id:
                customer_label = display
        await notify_channel_live_agent_queued(
            db,
            organization_id=bot.organization_id,
            tenant_id=tenant_id,
            session_id=session.id,
            channel=incoming.platform,
            customer_label=customer_label,
            preview=text,
        )
        return True

    reply = await _shop_channel_ai_reply(
        db,
        tenant_id=tenant_id,
        session_id=session.id,
        conversation_id=session.conversation_id,
        message=text,
        default_kb_id=bot.default_kb_id,
        organization_id=bot.organization_id,
    )

    is_first = (
        await conversation_repo.count_messages(db, session.conversation_id) == 0
    )
    if is_first:
        reply = append_live_agent_escalate_hint(reply)

    await conversation_repo.create_message(
        db,
        conversation_id=session.conversation_id,
        role="user",
        content=text,
    )
    await conversation_repo.create_message(
        db,
        conversation_id=session.conversation_id,
        role="assistant",
        content=reply,
    )
    await channel_session_repo.touch(db, session)
    await send_shop_channel_text(db, bot=bot, incoming=incoming, text=reply)
    return True


async def _shop_channel_ai_reply(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    conversation_id: UUID,
    message: str,
    default_kb_id: UUID | None,
    organization_id: UUID | None = None,
) -> str:
    widget_out = await try_native_widget_chat(
        tenant_id=tenant_id,
        data=ShopWidgetChatIn(
            session_id=session_id,
            message=message,
            kb_id=default_kb_id,
        ),
        db=db,
    )
    if widget_out is not None and (widget_out.reply or "").strip():
        return widget_out.reply.strip()

    llm_reply = await try_shop_channel_llm_reply(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message=message,
    )
    if llm_reply:
        return llm_reply

    native_agent = await try_shop_channel_agent_native_reply(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        message=message,
        organization_id=organization_id,
    )
    if native_agent:
        return native_agent

    agent_reply = await try_shop_channel_agent_strangler_reply(
        tenant_id=tenant_id,
        session_id=session_id,
        message=message,
        kb_id=default_kb_id,
        organization_id=organization_id,
    )
    if agent_reply:
        return agent_reply

    return _CHANNEL_LLM_FALLBACK_VI
