"""Persistence helpers for room thread lifecycle and per-reader state."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.conversation import Message
from app.db.models.room_thread import RoomThread, RoomThreadFollow, RoomThreadRead


@dataclass(frozen=True)
class ThreadReaderSummary:
    """A thread's lifecycle and read state for one authorized human."""

    state: str
    following: bool
    unread: int


async def get_thread(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_id: UUID,
    lock: bool = False,
) -> RoomThread | None:
    """Read one persisted lifecycle row, optionally locking it for mutation."""
    query = select(RoomThread).where(
        RoomThread.organization_id == organization_id,
        RoomThread.conversation_id == conversation_id,
        RoomThread.root_message_id == root_message_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def ensure_thread(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_id: UUID,
) -> RoomThread:
    """Create the implicit-open row only when a reader needs stored state."""
    await db.execute(
        pg_insert(RoomThread)
        .values(
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
        )
        .on_conflict_do_nothing()
    )
    row = await get_thread(
        db,
        organization_id=organization_id,
        conversation_id=conversation_id,
        root_message_id=root_message_id,
        lock=True,
    )
    if row is None:
        raise RuntimeError("Room thread lifecycle row could not be read back")
    return row


async def set_following(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_id: UUID,
    user_id: UUID,
    following: bool,
) -> bool:
    """Store an explicit follow or mute, including overrides to author defaults."""
    result = await db.execute(
        pg_insert(RoomThreadFollow)
        .values(
            id=uuid4(),
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
            user_id=user_id,
            following=following,
        )
        .on_conflict_do_update(
            index_elements=[
                RoomThreadFollow.organization_id,
                RoomThreadFollow.conversation_id,
                RoomThreadFollow.root_message_id,
                RoomThreadFollow.user_id,
            ],
            set_={"following": following, "updated_at": func.now()},
            where=RoomThreadFollow.following.is_distinct_from(following),
        )
        .returning(RoomThreadFollow.id)
    )
    await db.flush()
    return result.scalar_one_or_none() is not None


async def set_read_ordinal(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_id: UUID,
    user_id: UUID,
    ordinal: int,
) -> bool:
    """Advance, but never rewind, a reader's saved message-order snapshot."""
    result = await db.execute(
        pg_insert(RoomThreadRead)
        .values(
            id=uuid4(),
            organization_id=organization_id,
            conversation_id=conversation_id,
            root_message_id=root_message_id,
            user_id=user_id,
            last_read_ordinal=ordinal,
        )
        .on_conflict_do_update(
            index_elements=[
                RoomThreadRead.organization_id,
                RoomThreadRead.conversation_id,
                RoomThreadRead.root_message_id,
                RoomThreadRead.user_id,
            ],
            set_={
                "last_read_ordinal": func.greatest(RoomThreadRead.last_read_ordinal, ordinal),
                "updated_at": func.now(),
            },
            where=RoomThreadRead.last_read_ordinal < ordinal,
        )
        .returning(RoomThreadRead.id)
    )
    await db.flush()
    return result.scalar_one_or_none() is not None


async def summaries_for_roots(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_ids: set[UUID],
    user_id: UUID,
) -> dict[UUID, ThreadReaderSummary]:
    """Batch thread state and unread reply counts for one transcript page."""
    if not root_message_ids:
        return {}

    root = aliased(Message)
    reply = aliased(Message)
    follow = aliased(RoomThreadFollow)
    read = aliased(RoomThreadRead)

    explicit_follow = (
        select(follow.following)
        .where(
            follow.organization_id == organization_id,
            follow.conversation_id == conversation_id,
            follow.root_message_id == root.id,
            follow.user_id == user_id,
        )
        .correlate(root)
        .scalar_subquery()
    )
    authored_reply = (
        select(reply.id)
        .where(
            reply.conversation_id == conversation_id,
            reply.thread_root_message_id == root.id,
            reply.role == "user",
            reply.author_user_id == user_id,
        )
        .correlate(root)
        .exists()
    )
    default_follow = or_(root.author_user_id == user_id, authored_reply)
    cursor = (
        select(read.last_read_ordinal)
        .where(
            read.organization_id == organization_id,
            read.conversation_id == conversation_id,
            read.root_message_id == root.id,
            read.user_id == user_id,
        )
        .correlate(root)
        .scalar_subquery()
    )
    unread_replies = (
        select(func.count(reply.id))
        .where(
            reply.conversation_id == conversation_id,
            reply.thread_root_message_id == root.id,
            reply.ordinal > func.coalesce(cursor, root.ordinal),
            reply.role.in_(("user", "assistant")),
            or_(reply.author_user_id.is_(None), reply.author_user_id != user_id),
        )
        .correlate(root)
        .scalar_subquery()
    )
    effective_follow = func.coalesce(explicit_follow, default_follow, False)
    result = await db.execute(
        select(
            root.id,
            func.coalesce(RoomThread.state, "open"),
            effective_follow,
            case((effective_follow, func.least(unread_replies, 100)), else_=0),
        )
        .outerjoin(
            RoomThread,
            and_(
                RoomThread.organization_id == organization_id,
                RoomThread.conversation_id == conversation_id,
                RoomThread.root_message_id == root.id,
            ),
        )
        .where(
            root.conversation_id == conversation_id,
            root.id.in_(root_message_ids),
            root.thread_root_message_id.is_(None),
        )
    )
    return {
        root_id: ThreadReaderSummary(state=state, following=following, unread=unread)
        for root_id, state, following, unread in result.all()
    }


async def follower_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    root_message_id: UUID,
) -> set[UUID]:
    """Resolve explicit followers and authors who follow by participating."""
    root = aliased(Message)
    reply = aliased(Message)
    explicit_false = select(RoomThreadFollow.user_id).where(
        RoomThreadFollow.organization_id == organization_id,
        RoomThreadFollow.conversation_id == conversation_id,
        RoomThreadFollow.root_message_id == root_message_id,
        RoomThreadFollow.following.is_(False),
    )
    explicit_true = await db.scalars(
        select(RoomThreadFollow.user_id).where(
            RoomThreadFollow.organization_id == organization_id,
            RoomThreadFollow.conversation_id == conversation_id,
            RoomThreadFollow.root_message_id == root_message_id,
            RoomThreadFollow.following.is_(True),
        )
    )
    implicit = await db.scalars(
        select(root.author_user_id)
        .where(
            root.conversation_id == conversation_id,
            root.id == root_message_id,
            root.role == "user",
            root.author_user_id.is_not(None),
            ~explicit_false.where(RoomThreadFollow.user_id == root.author_user_id).exists(),
        )
        .union(
            select(reply.author_user_id).where(
                reply.conversation_id == conversation_id,
                reply.thread_root_message_id == root_message_id,
                reply.role == "user",
                reply.author_user_id.is_not(None),
                ~explicit_false.where(RoomThreadFollow.user_id == reply.author_user_id).exists(),
            )
        )
    )
    return set(explicit_true.all()) | {user_id for user_id in implicit.all() if user_id is not None}
