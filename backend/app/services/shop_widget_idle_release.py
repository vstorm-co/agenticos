"""Idle auto-release for widget live-agent human sessions (D3 B54)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.db.models.shop_widget_handling import ShopWidgetHandling
from app.services.shop_channel_handling import HANDLING_MODE_AI, HANDLING_MODE_HUMAN
from app.services.shop_widget_customer import WIDGET_CONVERSATION_TITLE
from app.services.shop_widget_studio_handling import (
    _handling_conversation_ids,
    apply_handling_update,
)


async def _max_message_at_for_conversations(
    db: AsyncSession,
    conversation_ids: list[UUID],
) -> datetime | None:
    if not conversation_ids:
        return None
    return await db.scalar(
        select(func.max(Message.created_at)).where(Message.conversation_id.in_(conversation_ids))
    )


async def release_idle_widget_sessions_for_organization(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    idle_before: datetime,
) -> int:
    """Release widget human sessions idle since last message (session-aware)."""
    result = await db.execute(
        select(ShopWidgetHandling)
        .join(Conversation, ShopWidgetHandling.conversation_id == Conversation.id)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            or_(
                Conversation.title == WIDGET_CONVERSATION_TITLE,
                Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
            ),
            ShopWidgetHandling.handling_mode == HANDLING_MODE_HUMAN,
            ShopWidgetHandling.claimed_at.is_not(None),
        )
    )
    rows = list(result.scalars().all())
    seen_sessions: set[UUID] = set()
    released = 0
    for row in rows:
        conv_ids = await _handling_conversation_ids(
            db,
            organization_id=organization_id,
            tenant_id=tenant_id,
            conversation_id=row.conversation_id,
        )
        session_key = min(conv_ids)
        if session_key in seen_sessions:
            continue
        seen_sessions.add(session_key)
        last_message_at = await _max_message_at_for_conversations(db, conv_ids)
        activity_at = last_message_at if last_message_at is not None else row.claimed_at
        if activity_at is None or activity_at >= idle_before:
            continue
        await apply_handling_update(
            db,
            organization_id=organization_id,
            tenant_id=tenant_id,
            conversation_id=row.conversation_id,
            update_data={
                "handling_mode": HANDLING_MODE_AI,
                "claimed_by_user_id": None,
                "claimed_by_name": None,
                "claimed_at": None,
            },
        )
        released += 1
    return released
