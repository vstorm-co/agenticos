"""The stable private conversation a person has with one agent (#2575).

`open` returns it, creating it the first time. Only a person who may see the agent
gets one - a miss and a denial are the same 404 - and it is always the caller's
own: the key is the caller, never a parameter.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.repositories import agent_repo, conversation_repo, primary_conversation_repo
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
        self,
        *,
        organization_id: UUID,
        user_id: UUID,
        agent_id: UUID,
        title: str | None = None,
    ) -> UUID:
        """The conversation this person has with this agent, created on first use.

        For a caller that has already decided the person may talk to the agent - a linked
        channel identity the router admitted - and so asks no permission question here.
        """
        existing = await primary_conversation_repo.get_conversation_id(
            self.db, organization_id=organization_id, user_id=user_id, agent_id=agent_id
        )
        if existing is not None:
            return existing
        if title is None:
            # Named for the agent, like one opened from the console, wherever it was
            # first reached: a person finds it in their chat list by who it is with.
            agent = await agent_repo.get(self.db, agent_id, organization_id=organization_id)
            assert agent is not None, "the key names an agent that exists"
            title = agent.name
        conversation = await conversation_repo.create_conversation(
            self.db, organization_id=organization_id, user_id=user_id, title=title
        )
        winner = await primary_conversation_repo.claim(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation.id,
        )
        if winner != conversation.id:
            await conversation_repo.delete_conversation(self.db, db_conversation=conversation)
        return winner
