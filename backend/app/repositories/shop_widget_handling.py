"""Shop widget handling repository."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.shop_widget_handling import ShopWidgetHandling
from app.services.shop_channel_handling import HANDLING_MODE_AI
from app.services.shop_widget_customer import WIDGET_CONVERSATION_TITLE


async def get_by_conversation_id(
    db: AsyncSession,
    conversation_id: UUID,
) -> ShopWidgetHandling | None:
    return await db.get(ShopWidgetHandling, conversation_id)


async def get_or_create_ai(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> ShopWidgetHandling:
    row = await get_by_conversation_id(db, conversation_id)
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = ShopWidgetHandling(
        conversation_id=conversation_id,
        handling_mode=HANDLING_MODE_AI,
        updated_at=now,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def update(
    db: AsyncSession,
    *,
    row: ShopWidgetHandling,
    update_data: dict,
) -> ShopWidgetHandling:
    for field, value in update_data.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def count_by_handling_mode_for_organization(
    db: AsyncSession,
    organization_id: UUID,
    *,
    handling_mode: str,
) -> int:
    query = (
        select(func.count())
        .select_from(ShopWidgetHandling)
        .join(Conversation, ShopWidgetHandling.conversation_id == Conversation.id)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.user_id.is_(None),
            or_(
                Conversation.title == WIDGET_CONVERSATION_TITLE,
                Conversation.title.like(f"{WIDGET_CONVERSATION_TITLE}|%"),
            ),
            ShopWidgetHandling.handling_mode == handling_mode,
        )
    )
    result = await db.scalar(query)
    return int(result or 0)
