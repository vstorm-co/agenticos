"""Data access for a reader's pinned messages."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Message
from app.db.models.conversation_message_pin import ConversationMessagePin


async def set_message_pin(
    db: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    pinned: bool,
) -> None:
    """Pin or unpin idempotently, including overlapping requests and retries."""
    if pinned:
        statement = pg_insert(ConversationMessagePin).values(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        await db.execute(
            statement.on_conflict_do_nothing(
                index_elements=["user_id", "conversation_id", "message_id"]
            )
        )
    else:
        await db.execute(
            sql_delete(ConversationMessagePin).where(
                ConversationMessagePin.user_id == user_id,
                ConversationMessagePin.conversation_id == conversation_id,
                ConversationMessagePin.message_id == message_id,
            )
        )
    await db.flush()


async def get_message_pin(
    db: AsyncSession, *, user_id: UUID, conversation_id: UUID, message_id: UUID
) -> ConversationMessagePin | None:
    """Read one reader's bookmark after an idempotent pin request."""
    result = await db.execute(
        select(ConversationMessagePin).where(
            ConversationMessagePin.user_id == user_id,
            ConversationMessagePin.conversation_id == conversation_id,
            ConversationMessagePin.message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


async def list_message_pins(
    db: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    skip: int,
    limit: int,
) -> tuple[list[tuple[ConversationMessagePin, Message]], int]:
    """Read one bounded page of live message metadata and the total pin count."""
    result = await db.execute(
        select(ConversationMessagePin, Message)
        .join(
            Message,
            (Message.conversation_id == ConversationMessagePin.conversation_id)
            & (Message.id == ConversationMessagePin.message_id),
        )
        .where(
            ConversationMessagePin.user_id == user_id,
            ConversationMessagePin.conversation_id == conversation_id,
        )
        .order_by(ConversationMessagePin.created_at.desc(), Message.ordinal.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.all())
    total = await db.scalar(
        select(func.count())
        .select_from(ConversationMessagePin)
        .where(
            ConversationMessagePin.user_id == user_id,
            ConversationMessagePin.conversation_id == conversation_id,
        )
    )
    return items, total or 0


async def message_pin_ids(
    db: AsyncSession,
    *,
    user_id: UUID,
    conversation_id: UUID,
    message_ids: Collection[UUID],
) -> set[UUID]:
    """Which messages on this transcript page this reader pinned, in one query."""
    if not message_ids:
        return set()
    result = await db.execute(
        select(ConversationMessagePin.message_id).where(
            ConversationMessagePin.user_id == user_id,
            ConversationMessagePin.conversation_id == conversation_id,
            ConversationMessagePin.message_id.in_(set(message_ids)),
        )
    )
    return set(result.scalars().all())
