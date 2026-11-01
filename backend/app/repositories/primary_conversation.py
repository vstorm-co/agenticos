"""The stable private conversation per person, organization and agent (PostgreSQL async)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.primary_conversation import PrimaryConversation


async def get_conversation_id(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, agent_id: UUID
) -> UUID | None:
    """The conversation this person has with this agent, if one was ever opened."""
    return await db.scalar(
        select(PrimaryConversation.conversation_id).where(
            PrimaryConversation.organization_id == organization_id,
            PrimaryConversation.user_id == user_id,
            PrimaryConversation.agent_id == agent_id,
        )
    )


async def claim(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    agent_id: UUID,
    conversation_id: UUID,
) -> UUID:
    """Record `conversation_id` as the person's own, and return the one that holds the key.

    Two requests opening it together both reach here: the primary key picks one winner and
    the other's insert does nothing, so the value returned is the winner's - which is the
    caller's own only when it won, and the caller deletes its spare when it did not.
    """
    await db.execute(
        pg_insert(PrimaryConversation)
        .values(
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )
        .on_conflict_do_nothing()
    )
    winner = await get_conversation_id(
        db, organization_id=organization_id, user_id=user_id, agent_id=agent_id
    )
    assert winner is not None, "the insert, or a concurrent one, left a row"
    return winner
