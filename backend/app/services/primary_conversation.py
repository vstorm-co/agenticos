"""The stable private conversation a person has with one agent (#2575).

`open` returns it, creating it the first time. Only a person who may see the agent
gets one - a miss and a denial are the same 404 - and it is always the caller's
own: the key is the caller, never a parameter.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.primary_conversation import PrimaryConversation
from app.repositories import agent_repo, conversation_repo
from app.services.access import AGENT, resolve_access


class PrimaryConversationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def open(self, ctx: AuthContext, agent_id: UUID) -> UUID:
        """The caller's conversation with this agent, created on first use.

        Raises:
            NotFoundError: No such agent, or the caller may not see it.
        """
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None or not await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_VIEW, resource_type=AGENT
        ):
            raise NotFoundError(message="Agent not found", details={"agent_id": agent_id})
        return await self.ensure(
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            agent_id=agent_id,
            title=agent.name,
        )

    async def ensure(
        self, *, organization_id: UUID, user_id: UUID, agent_id: UUID, title: str | None
    ) -> UUID:
        """The conversation this person has with this agent, created on first use.

        For a caller that has already decided the person may talk to the agent - a linked
        channel identity the router admitted - and so asks no permission question here.
        """
        key = (
            PrimaryConversation.organization_id == organization_id,
            PrimaryConversation.user_id == user_id,
            PrimaryConversation.agent_id == agent_id,
        )
        existing = await self.db.scalar(select(PrimaryConversation.conversation_id).where(*key))
        if existing is not None:
            return existing
        conversation = await conversation_repo.create_conversation(
            self.db, organization_id=organization_id, user_id=user_id, title=title
        )
        # Two tabs opening it together both reach here: the primary key picks one
        # winner, and the loser reads the winner's row and drops its own.
        await self.db.execute(
            pg_insert(PrimaryConversation)
            .values(
                organization_id=organization_id,
                user_id=user_id,
                agent_id=agent_id,
                conversation_id=conversation.id,
            )
            .on_conflict_do_nothing()
        )
        winner = await self.db.scalar(select(PrimaryConversation.conversation_id).where(*key))
        assert winner is not None, "the insert or a concurrent one left a row"
        if winner != conversation.id:
            await self.db.delete(conversation)
            await self.db.flush()
        return winner
