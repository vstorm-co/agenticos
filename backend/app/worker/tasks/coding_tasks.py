"""Undo a coding task after its reservation commits, then reconcile uncertain attempts."""

from datetime import UTC, datetime

from pydantic_ai.workspaces import WorkspaceRef
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, AuthorizationError, BadRequestError
from app.db.models.coding_task_change import CodingTaskChange
from app.db.session import get_worker_db_context
from app.repositories import background_job as job_repo
from app.repositories import coding_task_change as change_repo
from app.schemas.coding_task_change import ChangedFile
from app.services import _coding_task_revert
from app.services.api_key import job_context
from app.services.coding_task_changes import CodingTaskChangeService
from app.services.conversation import ConversationService
from app.services.sandbox_workspace import SandboxWorkspaceService
from app.worker.attempt import current_attempt_number
from app.worker.jobs import RevertCodingTask


async def _owned(
    db: AsyncSession, payload: RevertCodingTask, *, fence: int
) -> CodingTaskChange | None:
    change = await change_repo.get_in_organization(
        db, payload.change_id, organization_id=payload.organization_id
    )
    if change is None or change.reverted_at is not None or change.revert_job_id is None:
        return None
    job_id = change.revert_job_id
    job = await job_repo.get_for_attempt(db, job_id, fence=fence)
    if job is None or job.payload.get("claim_id") != str(payload.claim_id):
        return None
    locked = await change_repo.get_in_organization(
        db, payload.change_id, organization_id=payload.organization_id, for_update=True
    )
    if locked is None or locked.revert_job_id != job_id or locked.reverted_at is not None:
        return None
    return locked


async def revert_coding_task(payload: RevertCodingTask) -> None:
    """Keep no connection or row lock while the workspace command runs.

    A lost worker or response leaves the durable reservation in place. Another
    attempt checks complete before/after states under a workspace file lock;
    it never blindly applies a reverse patch a second time.
    """
    fence = current_attempt_number()
    async with get_worker_db_context() as db:
        change = await _owned(db, payload, fence=fence)
        if change is None:
            return
        ctx = await job_context(
            db,
            organization_id=payload.organization_id,
            user_id=payload.user_id,
            api_key_id=payload.api_key_id,
        )
        if ctx is None:
            raise AuthorizationError(
                message="The revert requester is no longer an active member", details={}
            )
        await CodingTaskChangeService(db).get(ctx, change.id)
        await ConversationService(db).get_conversation(
            change.conversation_id,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            for_write=True,
            turn=True,
            include_favourite=False,
            ctx=ctx,
        )
        if (
            not change.snapshot_isolated
            or change.workspace_ref is None
            or not change.revert_patch
            or change.truncated
            or change.omitted
        ):
            raise BadRequestError(
                message="This task has no isolated complete snapshot to revert", details={}
            )
        files = [ChangedFile.model_validate(file) for file in change.files]
        patch = change.revert_patch
        reconcile = change.revert_started_at is not None
        async with SandboxWorkspaceService(db).open_recorded(
            ctx, conversation_id=change.conversation_id, ref=WorkspaceRef(**change.workspace_ref)
        ) as workspace:
            change.revert_started_at = change.revert_started_at or datetime.now(UTC)
            await change_repo.save(db, change)
            await db.commit()
            failure: dict[str, object] | None = None
            try:
                await _coding_task_revert.revert(workspace, files, patch, reconcile=reconcile)
            except (AlreadyExistsError, BadRequestError) as refused:
                paths = (refused.details or {}).get("conflicting_files", [])
                failure = {"conflicting_files": paths}
            # Lock the queue attempt first, then its domain row. A worker that
            # lost its lease cannot settle or audit another attempt's result.
            current = await _owned(db, payload, fence=fence)
            if current is None:
                return
            if failure is not None:
                current.revert_failure = failure
                current.revert_job_id = None
                # A definite pre-write refusal is safe to try afresh later.
                current.revert_started_at = None
                await change_repo.save(db, current)
                return
            await change_repo.mark_reverted(db, change=current)
            await record_audit(
                db,
                actor_user_id=ctx.user_id,
                organization_id=ctx.organization_id,
                action="coding_task.revert",
                target_type="coding_task_change",
                target_id=str(current.id),
                details={"conversation_id": str(current.conversation_id), "file_count": len(files)},
            )
