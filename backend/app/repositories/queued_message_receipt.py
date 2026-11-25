"""Tenant and owner scoped reads for accepted chat queue receipts."""

from uuid import UUID

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accepted_queued_message import AcceptedQueuedMessage
from app.db.models.channel_session import ChannelSession
from app.db.models.chat_file import ChatFile
from app.db.models.conversation import Message
from app.db.models.conversation_task import ConversationTask


async def is_channel_conversation(db: AsyncSession, conversation_id: UUID) -> bool:
    """Whether a conversation is backed by an external channel session."""
    return bool(
        await db.scalar(select(exists().where(ChannelSession.conversation_id == conversation_id)))
    )


async def get(
    db: AsyncSession,
    receipt_id: UUID,
    *,
    organization_id: UUID,
    requester_id: UUID | None = None,
    lock: bool = False,
) -> AcceptedQueuedMessage | None:
    query = select(AcceptedQueuedMessage).where(
        AcceptedQueuedMessage.id == receipt_id,
        AcceptedQueuedMessage.organization_id == organization_id,
    )
    if requester_id is not None:
        query = query.where(AcceptedQueuedMessage.requester_id == requester_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def for_client_key(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requester_id: UUID,
    conversation_id: UUID,
    client_queue_id: UUID,
    lock: bool = False,
) -> AcceptedQueuedMessage | None:
    query = select(AcceptedQueuedMessage).where(
        AcceptedQueuedMessage.organization_id == organization_id,
        AcceptedQueuedMessage.requester_id == requester_id,
        AcceptedQueuedMessage.conversation_id == conversation_id,
        AcceptedQueuedMessage.client_queue_id == client_queue_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def add_if_absent(db: AsyncSession, receipt: AcceptedQueuedMessage) -> AcceptedQueuedMessage:
    """Insert one receipt, waiting for a concurrent identical key to settle."""
    await db.execute(
        insert(AcceptedQueuedMessage)
        .values(
            id=receipt.id,
            organization_id=receipt.organization_id,
            conversation_id=receipt.conversation_id,
            requester_id=receipt.requester_id,
            client_queue_id=receipt.client_queue_id,
            agent_id=receipt.agent_id,
            payload=receipt.payload,
            payload_hash=receipt.payload_hash,
            state=receipt.state,
        )
        .on_conflict_do_nothing(constraint="uq_accepted_queue_client_key")
    )
    saved = await for_client_key(
        db,
        organization_id=receipt.organization_id,
        requester_id=receipt.requester_id,
        conversation_id=receipt.conversation_id,
        client_queue_id=receipt.client_queue_id,
        lock=True,
    )
    if saved is None:
        raise RuntimeError("Accepted queue receipt was not visible after insertion")
    return saved


async def pending_for_conversation(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID
) -> list[AcceptedQueuedMessage]:
    """Pending user work for the fresh-chat guard; this function never mutates rows."""
    result = await db.scalars(
        select(AcceptedQueuedMessage)
        .where(
            AcceptedQueuedMessage.organization_id == organization_id,
            AcceptedQueuedMessage.conversation_id == conversation_id,
            AcceptedQueuedMessage.state.in_(("pending", "steering")),
        )
        .order_by(AcceptedQueuedMessage.created_at, AcceptedQueuedMessage.id)
        .limit(1)
    )
    return list(result.all())


async def pending_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requester_id: UUID,
    conversation_id: UUID,
    cursor: UUID | None = None,
) -> list[AcceptedQueuedMessage]:
    query = select(AcceptedQueuedMessage).where(
        AcceptedQueuedMessage.organization_id == organization_id,
        AcceptedQueuedMessage.requester_id == requester_id,
        AcceptedQueuedMessage.conversation_id == conversation_id,
        AcceptedQueuedMessage.state.in_(("pending", "steering")),
    )
    if cursor is not None:
        anchor = await db.scalar(
            select(AcceptedQueuedMessage).where(
                AcceptedQueuedMessage.id == cursor,
                AcceptedQueuedMessage.organization_id == organization_id,
                AcceptedQueuedMessage.requester_id == requester_id,
                AcceptedQueuedMessage.conversation_id == conversation_id,
            )
        )
        if anchor is None:
            return []
        query = query.where(
            or_(
                AcceptedQueuedMessage.created_at > anchor.created_at,
                (AcceptedQueuedMessage.created_at == anchor.created_at)
                & (AcceptedQueuedMessage.id > anchor.id),
            )
        )
    result = await db.scalars(
        query.order_by(AcceptedQueuedMessage.created_at, AcceptedQueuedMessage.id).limit(101)
    )
    return list(result.all())


async def pending_count(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requester_id: UUID,
    conversation_id: UUID,
) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(AcceptedQueuedMessage)
            .where(
                AcceptedQueuedMessage.organization_id == organization_id,
                AcceptedQueuedMessage.requester_id == requester_id,
                AcceptedQueuedMessage.conversation_id == conversation_id,
                AcceptedQueuedMessage.state.in_(("pending", "steering")),
            )
        )
        or 0
    )


async def files_for_owner(
    db: AsyncSession,
    file_ids: set[UUID],
    *,
    user_id: UUID,
    lock: bool = False,
) -> list[ChatFile]:
    query = (
        select(ChatFile)
        .where(ChatFile.id.in_(file_ids), ChatFile.user_id == user_id)
        .order_by(ChatFile.id)
    )
    if lock:
        query = query.with_for_update()
    return list((await db.scalars(query)).all())


async def reserve_files(
    db: AsyncSession,
    file_ids: set[UUID],
    *,
    user_id: UUID,
    receipt_id: UUID,
) -> set[UUID]:
    if not file_ids:
        return set()
    await db.execute(
        update(ChatFile)
        .where(
            ChatFile.id.in_(file_ids),
            ChatFile.user_id == user_id,
            ChatFile.message_id.is_(None),
            ChatFile.queue_receipt_id.is_(None),
        )
        .values(queue_receipt_id=receipt_id)
    )
    result = await db.scalars(
        select(ChatFile.id).where(
            ChatFile.id.in_(file_ids),
            ChatFile.user_id == user_id,
            ChatFile.message_id.is_(None),
            ChatFile.queue_receipt_id == receipt_id,
        )
    )
    return set(result.all())


async def release_files(
    db: AsyncSession,
    file_ids: list[UUID],
    *,
    user_id: UUID,
    receipt_id: UUID,
) -> None:
    if file_ids:
        await db.execute(
            update(ChatFile)
            .where(
                ChatFile.id.in_(file_ids),
                ChatFile.user_id == user_id,
                ChatFile.queue_receipt_id == receipt_id,
                ChatFile.message_id.is_(None),
            )
            .values(queue_receipt_id=None)
        )


async def attach_reserved_files(
    db: AsyncSession,
    file_ids: set[UUID],
    *,
    user_id: UUID,
    receipt_id: UUID,
    message_id: UUID,
) -> set[UUID]:
    if not file_ids:
        return set()
    result = await db.execute(
        update(ChatFile)
        .where(
            ChatFile.id.in_(file_ids),
            ChatFile.user_id == user_id,
            ChatFile.message_id.is_(None),
            ChatFile.queue_receipt_id == receipt_id,
        )
        .values(message_id=message_id, queue_receipt_id=None)
        .returning(ChatFile.id)
    )
    return set(result.scalars().all())


async def quote_message(
    db: AsyncSession, *, conversation_id: UUID, message_id: UUID
) -> Message | None:
    return await db.scalar(
        select(Message)
        .where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.role.in_(("user", "assistant")),
        )
        .with_for_update(read=True)
    )


async def message_by_id(db: AsyncSession, message_id: UUID) -> Message | None:
    return await db.get(Message, message_id)


async def task_seed_message(
    db: AsyncSession,
    *,
    message_id: UUID,
    conversation_id: UUID,
    receipt_id: UUID,
    user_id: UUID,
) -> Message | None:
    """Load the exact user post created when a receipt became a task."""
    return await db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.accepted_queue_id == receipt_id,
            Message.author_user_id == user_id,
            Message.role == "user",
        )
    )


async def task_id_for_receipt(
    db: AsyncSession, *, organization_id: UUID, receipt_id: UUID
) -> UUID | None:
    return await db.scalar(
        select(ConversationTask.id).where(
            ConversationTask.organization_id == organization_id,
            ConversationTask.queue_receipt_id == receipt_id,
        )
    )


async def task_for_receipt(
    db: AsyncSession, *, organization_id: UUID, receipt_id: UUID
) -> ConversationTask | None:
    return await db.scalar(
        select(ConversationTask).where(
            ConversationTask.organization_id == organization_id,
            ConversationTask.queue_receipt_id == receipt_id,
        )
    )


async def unresolved_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    requester_id: UUID,
    conversation_id: UUID,
) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    AcceptedQueuedMessage.organization_id == organization_id,
                    AcceptedQueuedMessage.requester_id == requester_id,
                    AcceptedQueuedMessage.conversation_id == conversation_id,
                    AcceptedQueuedMessage.state.in_(("pending", "steering")),
                )
            )
        )
    )
