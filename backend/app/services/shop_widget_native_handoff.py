"""D3 B49 — widget handoff + poll on Agentra OLTP."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import conversation as conversation_repo
from app.repositories import organization_repo, shop_widget_handling as handling_repo
from app.repositories import shop_widget_conversation as widget_conv_repo
from app.schemas.shop_widget import ShopWidgetChatIn, ShopWidgetChatOut, ShopWidgetPollOut
from app.services import shop_widget_intents as intents
from app.services.shop_channel_handling import (
    HANDLING_MODE_HUMAN,
    HANDLING_MODE_QUEUED,
    STAFF_MESSAGE_MODEL,
    handoff_reply_for_platform,
    QUEUED_USER_ACK_VI,
)
from app.services.shop_widget_customer import parse_widget_customer_identity, resolve_customer_label
from app.services.shop_widget_queue_notify import notify_widget_live_agent_queued

logger = logging.getLogger(__name__)


def shop_native_widget_handoff_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_WIDGET_HANDOFF_ENABLED


async def get_handling_mode(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
) -> str:
    conv_id = widget_conv_repo.widget_conversation_id(
        tenant_id=tenant_id,
        session_id=session_id,
    )
    row = await handling_repo.get_by_conversation_id(db, conv_id)
    if row is None:
        return "ai"
    return row.handling_mode or "ai"


async def maybe_escalate_widget(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    message: str,
) -> str | None:
    row = await handling_repo.get_or_create_ai(db, conversation_id=conversation_id)
    if (row.handling_mode or "ai") != "ai":
        return None
    if not intents.wants_human_agent(message):
        return None
    await handling_repo.update(
        db,
        row=row,
        update_data={"handling_mode": HANDLING_MODE_QUEUED},
    )
    logger.info("widget_handoff_queued", extra={"conversation_id": str(conversation_id)})
    conv = await conversation_repo.get_conversation_by_id(db, conversation_id)
    identity = parse_widget_customer_identity(conv.title if conv else None)
    await notify_widget_live_agent_queued(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        customer_label=resolve_customer_label(identity=identity, first_user_messages=[message]),
        preview=message,
    )
    return handoff_reply_for_platform("widget")


async def persist_widget_exchange(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    user_message: str,
    assistant_reply: str,
    staff: bool = False,
) -> None:
    await conversation_repo.create_message(
        db,
        conversation_id=conversation_id,
        role="user",
        content=user_message,
    )
    if assistant_reply:
        await conversation_repo.create_message(
            db,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_reply,
            model_name=STAFF_MESSAGE_MODEL if staff else None,
        )


async def try_widget_handoff_chat_turn(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    data: ShopWidgetChatIn,
) -> ShopWidgetChatOut | None:
    """Handle queued/human modes and escalation; None → continue deterministic AI."""
    if not shop_native_widget_handoff_enabled():
        return None

    conv = await widget_conv_repo.ensure_widget_conversation(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=data.session_id,
        shopper_user_id=data.shopper_user_id,
        shopper_display_name=data.shopper_display_name,
        shopper_email=data.shopper_email,
    )
    mode = await get_handling_mode(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        session_id=data.session_id,
    )
    message = (data.message or "").strip()
    if not message:
        return None

    if mode == HANDLING_MODE_HUMAN:
        await conversation_repo.create_message(
            db,
            conversation_id=conv.id,
            role="user",
            content=message,
        )
        return ShopWidgetChatOut(
            reply="",
            session_id=data.session_id,
            handling_mode=HANDLING_MODE_HUMAN,
        )

    if mode == HANDLING_MODE_QUEUED:
        await conversation_repo.create_message(
            db,
            conversation_id=conv.id,
            role="user",
            content=message,
        )
        reply = (
            handoff_reply_for_platform("widget")
            if intents.wants_human_agent(message)
            else QUEUED_USER_ACK_VI
        )
        return ShopWidgetChatOut(
            reply=reply,
            session_id=data.session_id,
            handling_mode=HANDLING_MODE_QUEUED,
        )

    handoff = await maybe_escalate_widget(
        db,
        organization_id=organization_id,
        tenant_id=tenant_id,
        conversation_id=conv.id,
        message=message,
    )
    if handoff:
        await persist_widget_exchange(db, conversation_id=conv.id, user_message=message, assistant_reply=handoff)
        return ShopWidgetChatOut(
            reply=handoff,
            session_id=data.session_id,
            handling_mode=HANDLING_MODE_QUEUED,
        )

    return None


async def native_widget_poll_with_db(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    after_message_id: UUID | None = None,
) -> ShopWidgetPollOut:
    org = await organization_repo.get_by_minerp_tenant_id(db, tenant_id)
    if org is None:
        return ShopWidgetPollOut(session_id=session_id, handling_mode="ai", items=[])

    mode = await get_handling_mode(
        db,
        organization_id=org.id,
        tenant_id=tenant_id,
        session_id=session_id,
    )
    messages = await widget_conv_repo.list_messages_for_widget_session_poll(
        db,
        organization_id=org.id,
        tenant_id=tenant_id,
        session_id=session_id,
        after_message_id=after_message_id,
    )
    items: list[dict] = []
    for m in messages:
        sender_type = (
            "customer"
            if m.role == "user"
            else ("staff" if (m.model_name or "") == STAFF_MESSAGE_MODEL else "bot")
        )
        items.append(
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "sender_type": sender_type,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
        )
    return ShopWidgetPollOut(session_id=session_id, handling_mode=mode, items=items)
