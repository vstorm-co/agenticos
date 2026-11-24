"""A member's audited decision about a media submission nobody can prove either way.

A hold in `unknown` or `submitted` stays counted by `outstanding_usd` because the
platform cannot see whether the provider charged. Only a person reading the
provider's own billing can say, so this records what they report: a charge
becomes the operation's incurred fee (booked once by the existing ledger sweep),
and either answer releases the reservation and the byte hold.
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.workflow_run import NodeAttemptStatus
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.schemas.workflow_media import (
    WorkflowMediaCharged,
    WorkflowMediaOperationRead,
    WorkflowMediaResolve,
)
from app.services.workflow_media_read import WorkflowMediaReadService

RESOLVABLE_PHASES = frozenset({"unknown", "submitted"})


class WorkflowMediaResolutionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve(
        self, ctx: AuthContext, operation_id: UUID, body: WorkflowMediaResolve
    ) -> WorkflowMediaOperationRead:
        """Release one unresolved hold in the caller's organization.

        Raises:
            NotFoundError: No such operation in this organization.
            ConflictError: The operation is not an unresolved submission, a try is
                still collecting it, or the reported charge is below a fee
                already observed.
        """
        operation = await media_repo.get(
            self.db, operation_id, organization_id=ctx.organization_id, locked=True
        )
        if operation is None:
            raise NotFoundError(
                message="Media operation not found", details={"operation_id": operation_id}
            )
        if operation.phase not in RESOLVABLE_PHASES or operation.accounting_complete:
            raise ConflictError(
                message="Only an unresolved media submission can be resolved",
                details={"operation_id": operation.id, "phase": operation.phase},
            )
        latest = await run_repo.get_latest_attempt(self.db, node_run_id=operation.node_run_id)
        if latest is not None and latest.status == NodeAttemptStatus.IN_FLIGHT.value:
            raise ConflictError(
                message="A try is still collecting this media operation",
                details={"operation_id": operation.id},
            )
        released_usd = operation.held_usd
        changes: media_repo.MediaChanges = {
            "phase": "failed",
            "held_usd": Decimal(0),
            "held_bytes": 0,
            "accounting_complete": True,
        }
        if isinstance(body, WorkflowMediaCharged):
            # An observed fee is a fact; a report cannot lower it.
            if body.charged_usd < operation.incurred_usd:
                raise ConflictError(
                    message="The reported charge is below the fee already observed",
                    details={
                        "operation_id": operation.id,
                        "incurred_usd": str(operation.incurred_usd),
                    },
                )
            changes.update(
                incurred_usd=body.charged_usd,
                cost_source="reported",
                cost_evidence={"kind": operation.media_kind, "reported_by": "member"},
                reason_code="MEDIA_RESOLVED_CHARGED",
            )
        else:
            if operation.incurred_usd > 0:
                raise ConflictError(
                    message="A fee was already observed for this submission; resolve it as charged",
                    details={
                        "operation_id": operation.id,
                        "incurred_usd": str(operation.incurred_usd),
                    },
                )
            changes["reason_code"] = "MEDIA_RESOLVED_NOT_CHARGED"
        operation = await media_repo.change(
            self.db, operation.id, organization_id=ctx.organization_id, values=changes
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="workflow_media.hold_resolved",
            target_type="workflow_media_operation",
            target_id=str(operation.id),
            details={
                "workflow_run_id": str(operation.workflow_run_id),
                "node_run_id": str(operation.node_run_id),
                "outcome": body.outcome,
                "charged_usd": str(operation.incurred_usd),
                "released_usd": str(released_usd),
            },
        )
        projection = await WorkflowMediaReadService(self.db).for_nodes(
            organization_id=ctx.organization_id,
            workflow_run_id=operation.workflow_run_id,
            node_run_ids=[operation.node_run_id],
        )
        return projection[operation.node_run_id]
