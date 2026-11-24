"""Tenant-bound room message reactions and their batched transcript summaries."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import distinct, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message
from app.db.models.room_message_reaction import RoomMessageReaction
from app.schemas.room_reaction import RoomMessageReactionRead


async def get_room_message(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
) -> Message | None:
    """Find a visible human/assistant message inside the caller's tenant and room."""
    return await db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.organization_id == organization_id,
            Message.conversation_id == conversation_id,
            Message.id == message_id,
            Message.role.in_(("user", "assistant")),
        )
    )


async def get_for_user(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    user_id: UUID,
    emoji: str,
) -> RoomMessageReaction | None:
    return await db.scalar(
        select(RoomMessageReaction).where(
            RoomMessageReaction.organization_id == organization_id,
            RoomMessageReaction.conversation_id == conversation_id,
            RoomMessageReaction.message_id == message_id,
            RoomMessageReaction.user_id == user_id,
            RoomMessageReaction.emoji == emoji,
        )
    )


async def distinct_emoji_count(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
) -> int:
    return (
        await db.scalar(
            select(func.count(distinct(RoomMessageReaction.emoji))).where(
                RoomMessageReaction.organization_id == organization_id,
                RoomMessageReaction.conversation_id == conversation_id,
                RoomMessageReaction.message_id == message_id,
            )
        )
        or 0
    )


async def has_emoji(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    emoji: str,
) -> bool:
    return bool(
        await db.scalar(
            select(
                select(RoomMessageReaction.id)
                .where(
                    RoomMessageReaction.organization_id == organization_id,
                    RoomMessageReaction.conversation_id == conversation_id,
                    RoomMessageReaction.message_id == message_id,
                    RoomMessageReaction.emoji == emoji,
                )
                .exists()
            )
        )
    )


async def add(db: AsyncSession, reaction: RoomMessageReaction) -> None:
    db.add(reaction)
    await db.flush()


async def remove(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    user_id: UUID,
    emoji: str,
) -> bool:
    reaction = await get_for_user(
        db,
        organization_id=organization_id,
        conversation_id=conversation_id,
        message_id=message_id,
        user_id=user_id,
        emoji=emoji,
    )
    if reaction is None:
        return False
    await db.delete(reaction)
    await db.flush()
    return True


async def list_aggregates(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    message_ids: Sequence[UUID],
    user_id: UUID | None,
) -> dict[UUID, list[RoomMessageReactionRead]]:
    """Read one authorized page of messages' emoji totals in one query."""
    if not message_ids:
        return {}
    reacted_by_me = (
        func.bool_or(RoomMessageReaction.user_id == user_id)
        if user_id is not None
        else literal(False)
    )
    result = await db.execute(
        select(
            RoomMessageReaction.message_id,
            RoomMessageReaction.emoji,
            func.count(RoomMessageReaction.id).label("count"),
            reacted_by_me.label("reacted_by_me"),
        )
        .where(
            RoomMessageReaction.organization_id == organization_id,
            RoomMessageReaction.conversation_id == conversation_id,
            RoomMessageReaction.message_id.in_(message_ids),
        )
        .group_by(RoomMessageReaction.message_id, RoomMessageReaction.emoji)
        .order_by(func.min(RoomMessageReaction.created_at), RoomMessageReaction.emoji)
    )
    grouped: dict[UUID, list[RoomMessageReactionRead]] = {}
    for row in result:
        grouped.setdefault(row.message_id, []).append(
            RoomMessageReactionRead(
                emoji=row.emoji,
                count=row.count,
                reacted_by_me=bool(row.reacted_by_me),
            )
        )
    return grouped
