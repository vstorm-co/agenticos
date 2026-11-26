"""Current audiences relevant to cross-room thread context."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models.conversation import Conversation
from app.db.models.conversation_share import ConversationShare
from app.db.models.organization import OrganizationMember
from app.db.models.room_participant import RoomParticipant
from app.db.models.room_thread import RoomThread
from app.db.models.user import User


@dataclass(frozen=True)
class ActiveMemberContext:
    """The current organization authority for one active human member."""

    user_id: UUID
    role: str
    is_app_admin: bool


async def active_member_contexts(
    db: AsyncSession, *, organization_id: UUID
) -> list[ActiveMemberContext]:
    """List active organization members with their current role and admin flag."""
    rows = await db.execute(
        select(OrganizationMember.user_id, OrganizationMember.role, User.is_app_admin)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == organization_id,
            User.is_active.is_(True),
        )
        .order_by(OrganizationMember.user_id)
    )
    return [
        ActiveMemberContext(user_id=user_id, role=role, is_app_admin=is_app_admin)
        for user_id, role, is_app_admin in rows.all()
    ]


async def has_bearer_share(db: AsyncSession, *, conversation_id: UUID) -> bool:
    """Whether a conversation has a live token whose audience cannot be enumerated."""
    return bool(
        await db.scalar(
            select(ConversationShare.id)
            .where(
                ConversationShare.conversation_id == conversation_id,
                ConversationShare.share_token.is_not(None),
            )
            .limit(1)
        )
    )


async def agent_ids(db: AsyncSession, *, organization_id: UUID, conversation_id: UUID) -> set[UUID]:
    """The current agent roster for one tenant-scoped conversation."""
    rows = await db.scalars(
        select(RoomParticipant.agent_id).where(
            RoomParticipant.organization_id == organization_id,
            RoomParticipant.conversation_id == conversation_id,
            RoomParticipant.agent_id.is_not(None),
        )
    )
    return {agent_id for agent_id in rows.all() if agent_id is not None}


async def external_context_edges(
    db: AsyncSession,
    *,
    organization_id: UUID,
    destination_ids: set[UUID] | None = None,
) -> list[tuple[UUID, UUID]]:
    """List same-tenant room edges that import context from another conversation."""
    if destination_ids is not None and not destination_ids:
        return []
    statement = (
        select(RoomThread.conversation_id, RoomThread.context_source_conversation_id)
        .where(
            RoomThread.organization_id == organization_id,
            RoomThread.context_source_conversation_id.is_not(None),
            RoomThread.context_source_conversation_id != RoomThread.conversation_id,
        )
        .distinct()
    )
    if destination_ids is not None:
        statement = statement.where(RoomThread.conversation_id.in_(destination_ids))
    rows = await db.execute(statement)
    return [
        (destination_id, source_id)
        for destination_id, source_id in rows.all()
        if source_id is not None
    ]


async def conversations_by_ids(
    db: AsyncSession, *, organization_id: UUID, conversation_ids: set[UUID]
) -> dict[UUID, Conversation]:
    """Load tenant-scoped conversations for a bounded context-source closure."""
    if not conversation_ids:
        return {}
    rows = await db.scalars(
        select(Conversation)
        .options(
            load_only(
                Conversation.id,
                Conversation.organization_id,
                Conversation.user_id,
                Conversation.project_id,
                Conversation.room_visibility,
                Conversation.origin,
            )
        )
        .where(
            Conversation.organization_id == organization_id,
            Conversation.id.in_(conversation_ids),
        )
        .execution_options(populate_existing=True)
    )
    return {conversation.id: conversation for conversation in rows.all()}
