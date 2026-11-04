"""A workflow's log alert rules - list, add, change and remove.

Every route acts on one workflow, so none carries a `require(...)` gate:
`WorkflowLogAlertService` resolves `workflows:view` (list) or `workflows:edit`
(the rest) on that workflow and reports a refusal as "not found" - see the
`permissions-rbac` skill.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, WorkflowLogAlertSvc
from app.schemas.workflow_log_alert import (
    WorkflowLogAlertCreate,
    WorkflowLogAlertList,
    WorkflowLogAlertRead,
    WorkflowLogAlertUpdate,
)

router = APIRouter()


@router.get("/{workflow_id}/log-alerts", response_model=WorkflowLogAlertList)
async def list_log_alerts(workflow_id: UUID, service: WorkflowLogAlertSvc, ctx: Auth) -> Any:
    """The workflow's log alert rules, oldest first, each with its last alert."""
    return await service.list_rules(ctx, workflow_id)


@router.post(
    "/{workflow_id}/log-alerts",
    response_model=WorkflowLogAlertRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_log_alert(
    workflow_id: UUID, data: WorkflowLogAlertCreate, service: WorkflowLogAlertSvc, ctx: Auth
) -> Any:
    """A rule that tells its audience when at least `threshold` real-run lines matching it
    were written within `window_minutes`, at most once per window. `outcomes` and the step
    are checked against the steps of the workflow that carry a Quick Log. A workflow holds
    at most 25."""
    return await service.create_rule(ctx, workflow_id, data)


@router.patch("/{workflow_id}/log-alerts/{rule_id}", response_model=WorkflowLogAlertRead)
async def update_log_alert(
    workflow_id: UUID,
    rule_id: UUID,
    data: WorkflowLogAlertUpdate,
    service: WorkflowLogAlertSvc,
    ctx: Auth,
) -> Any:
    """Change the fields sent; `node_instance_id` and `message_contains` take `null` to clear."""
    return await service.update_rule(ctx, workflow_id, rule_id, data)


@router.delete("/{workflow_id}/log-alerts/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log_alert(
    workflow_id: UUID, rule_id: UUID, service: WorkflowLogAlertSvc, ctx: Auth
) -> None:
    """Remove a rule and the record of its alerts."""
    await service.delete_rule(ctx, workflow_id, rule_id)
