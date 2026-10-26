"""The decisions workflow runs wait on - what `human.approval` steps ask.

Organization-wide like the tool approvals queue, and gated the same way on
`approvals:decide`; a step that names its approvers narrows who may decide it,
which the service checks.
"""

from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, WorkflowApprovalSvc, WorkflowStatsSvc, require
from app.core.exceptions import BadRequestError
from app.core.permissions import Perm
from app.db.models.workflow_approval import WorkflowApprovalStatus
from app.schemas.workflow_approval import (
    WorkflowApprovalDecision,
    WorkflowApprovalList,
    WorkflowApprovalRead,
)
from app.schemas.workflow_stats import WorkflowApprovalsSummary

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
    created_from: datetime | None = Query(None, description="Asked at or after this instant"),
    created_to: datetime | None = Query(None, description="Asked at or before this instant"),
    oldest_first: bool = Query(True, description="The queue drains from the top"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Requests from workflow steps, oldest first - pending unless `status` asks otherwise.

    The decided ones read as a record with `oldest_first=false`, optionally within a
    `created_from` .. `created_to` window, as the tool approvals' record does.
    """
    return await service.queue(
        ctx,
        statuses=status or [],
        skip=skip,
        limit=limit,
        created_from=created_from,
        created_to=created_to,
        oldest_first=oldest_first,
    )


@router.get(
    "/stats",
    response_model=WorkflowApprovalsSummary,
    dependencies=[Depends(require(Perm.WORKFLOWS_VIEW))],
)
async def summarize_workflow_approvals(
    service: WorkflowStatsSvc,
    ctx: Auth,
    first: date = Query(alias="from", description="The first UTC day, inclusive"),
    last: date = Query(alias="to", description="The last UTC day, inclusive"),
) -> Any:
    """What the approval requests of real runs came to, over the UTC days asked.

    Counts every request asked on those days by how it ended - approved unchanged,
    approved edited, rejected, expired, cancelled, still pending - with the rates,
    the time to decide and how much approvers changed what they approved, and names
    the five workflows with the most requests. Test runs are left out. Gated on
    `workflows:view`, not `approvals:decide`, and only the workflows the caller may
    view are counted. Only counts and times are returned: no proposal, answer, note
    or title.
    """
    if last < first or (last - first).days > 366:
        raise BadRequestError(message="Ask for at most a year, from a day before the last")
    return await service.approvals_summary(ctx, first=first, last=last)


@router.post(
    "/{approval_id}",
    response_model=WorkflowApprovalRead,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def decide_workflow_approval(
    approval_id: UUID, data: WorkflowApprovalDecision, service: WorkflowApprovalSvc, ctx: Auth
) -> Any:
    """Approve or reject a step's request, which wakes the step. A decision is final.

    An editable step takes `final`, the version approved; any other step, and any
    rejection, refuses it with 422 naming `final`.
    """
    return await service.decide(
        ctx, approval_id, approved=data.approved, note=data.note, final=data.final
    )
