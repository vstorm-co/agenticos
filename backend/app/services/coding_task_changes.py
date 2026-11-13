"""What each coding-agent task changed, kept for the panel that shows the task (#2480).

The change set is captured in the sandbox (`app.agents.capabilities.coding_agent._changes`)
and recorded here; reading it back asks the question reading the task itself asks -
may this person read the conversation it ran in - and nothing wider.
"""

from uuid import UUID

from pydantic_ai.workspaces import WorkspaceRef
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.coding_task_change import CodingTaskChange
from app.repositories import agent_run as run_repo
from app.repositories import coding_task_change as change_repo
from app.schemas.coding_task_change import ChangedFile, ChangeSet, CodingTaskChangeRead
from app.services import _coding_task_revert
from app.services.conversation import ConversationService
from app.services.project_workspace_guard import project_for_workspace
from app.services.sandbox_workspace import SandboxWorkspaceService


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
        workspace_ref: WorkspaceRef | None = None,
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
            revert_patch=changes.revert_patch,
            workspace_ref=(
                {"provider": workspace_ref.provider, "id": workspace_ref.id}
                if workspace_ref is not None
                else None
            ),
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

    async def read(self, ctx: AuthContext, change_id: UUID) -> CodingTaskChangeRead:
        """A task's diff and whether this reader may currently revert it."""
        change = await self.get(ctx, change_id)
        readable = CodingTaskChangeRead.model_validate(change)
        if (
            change.truncated
            or change.omitted
            or not change.revert_patch
            or change.workspace_ref is None
            or change.reverted_at is not None
        ):
            return readable
        try:
            _coding_task_revert.manifests(readable.files)
            await SandboxWorkspaceService(self.db).recorded_for_task(
                ctx,
                conversation_id=change.conversation_id,
                ref=WorkspaceRef(**change.workspace_ref),
            )
        except NotFoundError, BadRequestError, AlreadyExistsError, AuthorizationError:
            return readable
        return readable.model_copy(update={"can_revert": True})

    async def revert(self, ctx: AuthContext, change_id: UUID) -> CodingTaskChangeRead:
        """Undo a complete task in its original workspace, refusing later file edits.

        Requires a person with edit access to the conversation and its workspace.
        Truncated, redacted and older display-only patches cannot restore files.
        A repeated successful request returns the original successful result.

        Raises:
            NotFoundError: The task or original workspace is unavailable to this caller.
            BadRequestError: The recorded change set cannot restore the full task.
            AlreadyExistsError: An affected file has changed; no file is reverted.
        """
        change = await self.get(ctx, change_id)
        conversation = await ConversationService(self.db).get_conversation(
            change.conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            for_write=True,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )
        if conversation.project_id is not None:
            # Project deletion takes this lock before cascading into task rows.
            await project_for_workspace(self.db, ctx, conversation.project_id)
        locked = await change_repo.get_in_organization(
            self.db, change_id, organization_id=ctx.organization_id, for_update=True
        )
        if locked is None:
            raise NotFoundError(message="Change set not found", details={"change_id": change_id})
        if locked.reverted_at is not None:
            return CodingTaskChangeRead.model_validate(locked)
        if (
            locked.truncated
            or locked.omitted
            or not locked.revert_patch
            or locked.workspace_ref is None
        ):
            raise BadRequestError(
                message="This task has no complete snapshot to revert", details={}
            )
        if await run_repo.has_running_in_conversation(
            self.db, organization_id=ctx.organization_id, conversation_id=locked.conversation_id
        ):
            raise AlreadyExistsError(
                message="Wait for the conversation's current run to finish before reverting",
                details={},
            )
        files = [ChangedFile.model_validate(file) for file in locked.files]
        async with SandboxWorkspaceService(self.db).open_recorded(
            ctx,
            conversation_id=locked.conversation_id,
            ref=WorkspaceRef(**locked.workspace_ref),
        ) as workspace:
            await _coding_task_revert.revert(workspace, files, locked.revert_patch)
        await change_repo.mark_reverted(self.db, change=locked)
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="coding_task.revert",
            target_type="coding_task_change",
            target_id=str(change_id),
            details={"conversation_id": str(locked.conversation_id), "file_count": len(files)},
        )
        return CodingTaskChangeRead.model_validate(locked)
