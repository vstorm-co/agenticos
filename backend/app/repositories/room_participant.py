"""Persistence helpers for conversation room rosters."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models.conversation import Conversation
from app.db.models.organization import OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.user import User
from app.repositories.conversation import LISTED_COLUMNS


async def list_for_conversation(
    db: AsyncSession, *, organization_id: UUID, conversation_id: UUID
) -> list[RoomParticipant]:
    """The current roster, ordered by when each principal joined."""
    result = await db.scalars(
        select(RoomParticipant)
        .where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == conversation_id,
        )
        .order_by(RoomParticipant.created_at, RoomParticipant.id)
    )
    return list(result.all())


async def has_member(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
) -> bool:
    """Whether this human currently belongs to the room roster."""
    return bool(
        await db.scalar(
            select(RoomParticipant.id)
            .where(
                RoomParticipant.organization_id == organization_id,
                RoomParticipant.conversation_id == conversation_id,
                RoomParticipant.user_id == user_id,
            )
            .limit(1)
        )
    )


async def has_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
) -> bool:
    """Whether this agent is currently on the room roster."""
    return bool(
        await db.scalar(
            select(RoomParticipant.id)
            .where(
                RoomParticipant.organization_id == organization_id,
                RoomParticipant.conversation_id == conversation_id,
                RoomParticipant.agent_id == agent_id,
            )
            .limit(1)
        )
    )


async def get_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
) -> RoomParticipant | None:
    """Resolve one room agent membership without crossing its tenant boundary."""
    return await db.scalar(
        select(RoomParticipant)
        .where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == conversation_id,
            RoomParticipant.agent_id == agent_id,
        )
        .limit(1)
    )


async def add(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    auto_reply: bool = False,
) -> tuple[RoomParticipant, bool]:
    """Insert one roster entry idempotently, returning whether it was new."""
    values = {
        "organization_id": organization_id,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "auto_reply": auto_reply,
    }
    inserted = await db.execute(
        pg_insert(RoomParticipant)
        .values(**values)
        .on_conflict_do_nothing()
        .returning(RoomParticipant.id)
    )
    created_id = inserted.scalar_one_or_none()
    await db.flush()
    row = await db.scalar(
        select(RoomParticipant).where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == conversation_id,
            *(
                [RoomParticipant.user_id == user_id]
                if user_id is not None
                else [RoomParticipant.agent_id == agent_id]
            ),
        )
    )
    if row is None:
        raise RuntimeError("Inserted room participant could not be read back")
    return row, created_id is not None


async def remove(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> bool:
    """Remove a principal from the roster, returning whether a row existed."""
    from sqlalchemy import delete

    query = delete(RoomParticipant).where(
        RoomParticipant.organization_id == organization_id,
        RoomParticipant.conversation_id == conversation_id,
    )
    if user_id is not None:
        query = query.where(RoomParticipant.user_id == user_id)
    elif agent_id is not None:
        query = query.where(RoomParticipant.agent_id == agent_id)
    else:
        raise ValueError("A user_id or agent_id is required")
    result = await db.execute(query.returning(RoomParticipant.id))
    await db.flush()
    return result.scalar_one_or_none() is not None


async def set_auto_reply(
    db: AsyncSession,
    *,
    organization_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    auto_reply: bool,
) -> bool:
    """Set an agent's explicit automatic-response preference."""
    from sqlalchemy import update

    result = await db.execute(
        update(RoomParticipant)
        .where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == conversation_id,
            RoomParticipant.agent_id == agent_id,
        )
        .values(auto_reply=auto_reply)
        .returning(RoomParticipant.id)
    )
    await db.flush()
    return result.scalar_one_or_none() is not None


async def user_conversation_ids(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> set[UUID]:
    """Room conversations the user joined, for the ordinary conversation list."""
    result = await db.scalars(
        select(RoomParticipant.conversation_id)
        .join(Conversation, Conversation.id == RoomParticipant.conversation_id)
        .where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.user_id == user_id,
            # A project is the access floor for its conversations. A roster
            # entry never restores visibility after project access is revoked.
            Conversation.project_id.is_(None),
        )
    )
    return set(result.all())


async def user_ids_in_conversations(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, conversation_ids: Collection[UUID]
) -> set[UUID]:
    """Candidates the user may read through a roster, in one bounded access query."""
    if not conversation_ids:
        return set()
    result = await db.scalars(
        select(RoomParticipant.conversation_id).where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id.in_(set(conversation_ids)),
            RoomParticipant.user_id == user_id,
        )
    )
    return set(result.all())


async def active_people(db: AsyncSession, *, organization_id: UUID) -> list[User]:
    """Active organization members the room picker may offer."""
    result = await db.scalars(
        select(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            OrganizationMember.organization_id == organization_id,
            User.is_active.is_(True),
        )
        .order_by(func.lower(func.coalesce(User.full_name, User.email)), User.id)
    )
    return list(result.all())


async def public_directory(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    skip: int,
    limit: int,
    excluded_conversation_ids: Collection[UUID] = frozenset(),
) -> tuple[list[Conversation], int]:
    """Page public non-project rooms this user has not joined."""
    joined = (
        select(RoomParticipant.id)
        .where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == Conversation.id,
            RoomParticipant.user_id == user_id,
        )
        .exists()
    )
    filters = (
        Conversation.organization_id == organization_id,
        Conversation.room_visibility == "public",
        Conversation.project_id.is_(None),
        Conversation.origin.is_(None),
        Conversation.is_archived.is_(False),
        Conversation.id.not_in(excluded_conversation_ids),
        ~joined,
    )
    total = await db.scalar(select(func.count(Conversation.id)).where(*filters)) or 0
    items = await db.scalars(
        select(Conversation)
        .options(load_only(*LISTED_COLUMNS, raiseload=True))
        .where(*filters)
        .order_by(
            func.coalesce(Conversation.updated_at, Conversation.created_at).desc(),
            Conversation.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    return list(items.all()), total


async def public_ids_in_conversations(
    db: AsyncSession, *, organization_id: UUID, conversation_ids: Collection[UUID]
) -> set[UUID]:
    """Which bounded candidates are public rooms, excluding legacy/project rows."""
    if not conversation_ids:
        return set()
    result = await db.scalars(
        select(Conversation.id).where(
            Conversation.organization_id == organization_id,
            Conversation.id.in_(set(conversation_ids)),
            Conversation.room_visibility == "public",
            Conversation.project_id.is_(None),
            Conversation.origin.is_(None),
        )
    )
    return set(result.all())
