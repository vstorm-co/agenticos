"""Reuse workflow principal and source authority, with the exact dispatch fence."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.workflow_run import (
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRunStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow_run as run_repo
from app.services.workflow_execution.agent_conversations import ChatSourceGuard
from app.services.workflow_execution.context import DispatchContext
from app.services.workflow_media._errors import MediaOperationError


async def fence(db: AsyncSession, current: DispatchContext, *, locked: bool = False) -> UUID:
    """A reclaimed/expired/closed outbox authorizes neither submission nor output."""
    if current.claim.lost or current.claim_token is None:
        raise MediaOperationError(
            "MEDIA_CLAIM_LOST", "This media dispatch no longer owns its claim"
        )
    outbox = (
        await run_repo.get_outbox_for_node_run_for_update(db, node_run_id=current.node_run_id)
        if locked
        else await run_repo.get_live_outbox(
            db, node_run_id=current.node_run_id, organization_id=current.organization_id
        )
    )
    if (
        outbox is None
        or outbox.organization_id != current.organization_id
        or outbox.workflow_run_id != current.workflow_run_id
        or outbox.claimed_by != current.claim_token
        or outbox.status != DispatchOutboxStatus.CLAIMED.value
        or outbox.lease_expires_at is None
        or outbox.lease_expires_at <= datetime.now(UTC)
    ):
        raise MediaOperationError(
            "MEDIA_CLAIM_LOST", "This media dispatch no longer owns its claim"
        )

    return current.claim_token


async def dispatch_rows(
    db: AsyncSession, current: DispatchContext, *, locked: bool = False
) -> tuple[WorkflowRun, NodeAttempt]:
    """A still-live canonical run/step/attempt; callers acquire file quota first."""
    run = (
        await run_repo.get_run_by_id_for_update(db, current.workflow_run_id)
        if locked
        else await run_repo.get_run(
            db, current.workflow_run_id, organization_id=current.organization_id
        )
    )
    node = (
        await run_repo.get_node_run_by_id_for_update(db, current.node_run_id)
        if locked
        else await run_repo.get_node_run_by_id(db, current.node_run_id)
    )
    if (
        run is None
        or run.organization_id != current.organization_id
        or WorkflowRunStatus(run.status).is_terminal
        or node is None
        or node.organization_id != current.organization_id
        or node.workflow_run_id != run.id
        or node.status != NodeRunStatus.RUNNING.value
    ):
        raise MediaOperationError("MEDIA_RUN_STOPPED", "This media run or step is no longer active")
    attempt = await run_repo.get_latest_attempt(db, node_run_id=node.id)
    if (
        attempt is None
        or attempt.organization_id != current.organization_id
        or attempt.attempt_no != current.attempt_no
        or attempt.status != NodeAttemptStatus.IN_FLIGHT.value
    ):
        raise MediaOperationError("MEDIA_ATTEMPT_REPLACED", "A later attempt owns this media step")
    await fence(db, current)
    return run, attempt


async def principal(db: AsyncSession, current: DispatchContext, run: WorkflowRun) -> AuthContext:
    # Import at the effect boundary, avoiding the registry -> handler -> dispatcher
    # cycle. This is the existing dispatcher authority, not a second implementation.
    from app.services.workflow_execution.dispatcher import current_principal

    auth = await current_principal(db, run)
    await ChatSourceGuard(db, current.chat_source).check()
    return auth
