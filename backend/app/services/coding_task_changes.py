"""What each coding-agent task changed, kept for the panel that shows the task (#2480).

The change set is captured in the sandbox (`app.agents.capabilities.coding_agent._changes`)
and recorded here; reading it back asks the question reading the task itself asks -
may this person read the conversation it ran in - and nothing wider.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.coding_task_change import CodingTaskChange
from app.repositories import coding_task_change as change_repo
from app.schemas.coding_task_change import ChangeSet
from app.services.conversation import ConversationService


class CodingTaskChangeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        changes: ChangeSet,
        *,
        organization_id: UUID,
        conversation_id: UUID,
        tool_call_id: str | None,
        harness: str,
    ) -> CodingTaskChange:
        """Keep one task's change set, in the conversation it ran in."""
        return await change_repo.create(
            self.db,
            organization_id=organization_id,
            conversation_id=conversation_id,
            tool_call_id=tool_call_id,
            harness=harness,
            files=[entry.model_dump(mode="json") for entry in changes.files],
            omitted=changes.omitted,
            truncated=changes.truncated,
        )

    async def get(self, ctx: AuthContext, change_id: UUID) -> CodingTaskChange:
        """One task's change set, for somebody who may read the conversation it ran in.

        The same reader check the transcript route makes - an owner, a participant,
        somebody it was shared with, a grant on a trigger's agent - so whoever sees
        the task's panel sees its diff, and nobody else. A change set in another
        organization, or in a conversation the caller may not read, is missing
        rather than forbidden. A caller who is no person reads none: with no
        `user_id` the conversation check would ask nothing.

        Raises:
            NotFoundError: If there is no such change set the caller may read.
        """
        missing = NotFoundError(message="Change set not found", details={"change_id": change_id})
        if ctx.user_id is None:
            raise missing
        change = await change_repo.get_in_organization(
            self.db, change_id, organization_id=ctx.organization_id
        )
        if change is None:
            raise missing
        try:
            await ConversationService(self.db).get_conversation(
                change.conversation_id,
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                include_favourite=False,
                ctx=ctx,
            )
        except NotFoundError:
            raise missing from None
        return change
