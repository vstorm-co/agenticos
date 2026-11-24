"""Proof for collection-only retries, with no independent dispatch authority."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.models.workflow_run import NodeAttempt
from app.repositories import workflow_media_operation as media_repo
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import collectable


async def current(
    db: AsyncSession, *, organization_id: UUID, node_run_id: UUID, locked: bool = False
) -> WorkflowMediaOperation | None:
    return await media_repo.current_for_node(
        db, organization_id=organization_id, node_run_id=node_run_id, locked=locked
    )


async def can_collect(db: AsyncSession, *, organization_id: UUID, node_run_id: UUID) -> bool:
    operation = await current(db, organization_id=organization_id, node_run_id=node_run_id)
    return operation is not None and collectable(operation)


async def orphaned(db: AsyncSession, attempt: NodeAttempt) -> bool:
    """Retain the effect's facts after lease loss; return only collection proof."""
    operation = await current(
        db, organization_id=attempt.organization_id, node_run_id=attempt.node_run_id, locked=True
    )
    if operation is None or operation.collector_attempt_id != attempt.id:
        return False
    if operation.phase == "prepared" and operation.submission_token is None:
        await media_repo.change(
            db,
            operation.id,
            organization_id=attempt.organization_id,
            values={
                "phase": "failed",
                "held_usd": Decimal(0),
                "held_bytes": 0,
                "accounting_complete": True,
                "reason_code": "MEDIA_DISPATCH_INTERRUPTED",
            },
        )
        return False
    if collectable(operation):
        return True
    if operation.phase == "submitting":
        await media_repo.change(
            db,
            operation.id,
            organization_id=attempt.organization_id,
            values={"phase": "unknown", "reason_code": "MEDIA_SUBMISSION_UNKNOWN"},
        )
    return False


async def explicit_retry(
    db: AsyncSession, *, organization_id: UUID, node_run_id: UUID, now: datetime
) -> None:
    operation = await current(
        db, organization_id=organization_id, node_run_id=node_run_id, locked=True
    )
    if operation is None or collectable(operation):
        return
    if operation.phase not in {"failed", "cancelled"}:
        raise MediaOperationError(
            "MEDIA_RECONCILIATION_REQUIRED",
            "This operation has no safe collection proof. A new run is a separate billable submission and retains this hold.",
        )
    await media_repo.change(
        db, operation.id, organization_id=organization_id, values={"superseded_at": now}
    )
