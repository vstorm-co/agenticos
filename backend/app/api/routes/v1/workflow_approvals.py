"""The decisions workflow runs wait on - what `human.approval` steps ask.

Organization-wide like the tool approvals queue, and gated the same way on
`approvals:decide`; a step that names its approvers narrows who may decide it,
which the service checks.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, WorkflowApprovalSvc, require
from app.core.permissions import Perm
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.schemas.workflow_approval import (
    WorkflowApprovalDecision,
    WorkflowApprovalList,
    WorkflowApprovalRead,
)

router = APIRouter()


@router.get(
    "",
    response_model=WorkflowApprovalList,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def list_workflow_approvals(
    service: WorkflowApprovalSvc,
    ctx: Auth,
    status: Annotated[list[WorkflowApprovalStatus] | None, Query()] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Requests from workflow steps, oldest first - pending unless `status` asks otherwise."""
    return await service.queue(ctx, statuses=status or [], skip=skip, limit=limit)


@router.post(
    "/{approval_id}",
    response_model=WorkflowApprovalRead,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def decide_workflow_approval(
    approval_id: UUID, data: WorkflowApprovalDecision, service: WorkflowApprovalSvc, ctx: Auth
) -> Any:
    """Approve or reject a step's request, which wakes the step. A decision is final."""
    return await service.decide(ctx, approval_id, approved=data.approved, note=data.note)
