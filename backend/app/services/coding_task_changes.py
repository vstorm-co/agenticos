"""What each coding-agent task changed, kept for the panel that shows the task (#2480).

The change set is captured in the sandbox (`app.agents.capabilities.coding_agent._changes`)
and recorded here; reading it back asks the question reading the task itself asks -
may this person read the conversation it ran in - and nothing wider.
"""

from uuid import UUID, uuid4

from pydantic_ai.workspaces import WorkspaceRef
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.db.models.coding_task_change import CodingTaskChange
from app.repositories import background_job as job_repo
from app.repositories import coding_task_change as change_repo
from app.schemas.coding_task_change import ChangeSet, CodingTaskChangeRead
from app.services import _coding_task_revert
from app.services.background_jobs import enqueue
from app.services.conversation import ConversationService
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.services.workspace_turn_guard import admit
from app.worker.jobs import REVERT_CODING_TASK, RevertCodingTask


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
        snapshot_isolated: bool = False,
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
            snapshot_isolated=snapshot_isolated,
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
        if change.revert_job_id is not None and change.reverted_at is None:
            job = await job_repo.get(self.db, change.revert_job_id)
            readable.revert_status = (
                "pending" if job is not None and job.status in ("queued", "running") else "unknown"
            )
        elif change.revert_failure is not None:
            readable.revert_status = "failed"
            paths = change.revert_failure.get("conflicting_files", [])
            if isinstance(paths, list):
                readable.revert_conflicting_files = [
                    path for path in paths if isinstance(path, str)
                ]
        if (
            change.truncated
            or change.omitted
            or not change.revert_patch
            or change.workspace_ref is None
            or change.reverted_at is not None
            or not change.snapshot_isolated
            or readable.revert_status == "pending"
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
        """Queue a recoverable undo in an isolated conversation workspace.

        Requires a person with edit access to the conversation and its workspace.
        Truncated, redacted and older display-only patches cannot restore files.
        The reservation and job commit together before external work starts.
        A repeated successful request returns the original successful result;
        an in-flight request is refused without waiting. An unknown outcome can
        be retried to reconcile the original file states.

        Raises:
            NotFoundError: The task or original workspace is unavailable to this caller.
            BadRequestError: The recorded change set cannot restore the full task.
            AlreadyExistsError: Another writer or revert currently holds the workspace.
        """
        change = await self.get(ctx, change_id)
        await ConversationService(self.db).get_conversation(
            change.conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            for_write=True,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )
        if change.reverted_at is not None:
            return CodingTaskChangeRead.model_validate(change)
        # A worker may briefly lock the task while preparing its attempt. A
        # duplicate must reject the committed reservation before taking that lock.
        if change.revert_job_id is not None:
            job = await job_repo.get(self.db, change.revert_job_id)
            if job is not None and job.status in ("queued", "running"):
                raise AlreadyExistsError(message="This task is already being reverted", details={})
        await admit(
            self.db,
            organization_id=ctx.organization_id,
            conversation_id=change.conversation_id,
            change_id=change_id,
        )
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
            or not locked.snapshot_isolated
        ):
            raise BadRequestError(
                message="This task has no complete snapshot to revert", details={}
            )
        if locked.revert_job_id is not None:
            job = await job_repo.get(self.db, locked.revert_job_id)
            if job is not None and job.status in ("queued", "running"):
                raise AlreadyExistsError(message="This task is already being reverted", details={})
        await SandboxWorkspaceService(self.db).recorded_for_task(
            ctx,
            conversation_id=locked.conversation_id,
            ref=WorkspaceRef(**locked.workspace_ref),
        )
        _coding_task_revert.manifests(CodingTaskChangeRead.model_validate(locked).files)
        assert ctx.user_id is not None, "get requires an authenticated person"
        job_id = await enqueue(
            self.db,
            REVERT_CODING_TASK,
            RevertCodingTask(
                organization_id=ctx.organization_id,
                change_id=change_id,
                user_id=ctx.user_id,
                claim_id=uuid4(),
                api_key_id=ctx.api_key_id,
            ),
            organization_id=ctx.organization_id,
            dedupe_key=f"coding-task-revert:{change_id}",
            dedupe_active=True,
            concurrency_key=f"coding-task-revert:{ctx.organization_id}",
        )
        if job_id is None:
            raise AlreadyExistsError(message="This task is already being reverted", details={})
        locked.revert_job_id = job_id
        locked.revert_failure = None
        await change_repo.save(self.db, locked)
        return CodingTaskChangeRead.model_validate(locked).model_copy(
            update={"revert_status": "pending"}
        )
