"""A model step's evals - its cases, trying them, and how a try went.

Every route acts on one workflow, so none carries a `require(...)` gate:
`WorkflowEvalService` resolves `workflows:edit` on that workflow and reports a
refusal as "not found" - see the `permissions-rbac` skill.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, WorkflowEvalSvc, limit_workflow_run
from app.schemas.workflow_eval import EvalCaseCreate, EvalCaseList, EvalCaseRead, EvalRunRead

router = APIRouter()


@router.get("/{workflow_id}/steps/{node_id}/evals", response_model=EvalCaseList)
async def list_step_evals(
    workflow_id: UUID, node_id: UUID, service: WorkflowEvalSvc, ctx: Auth
) -> Any:
    """The step's eval cases, oldest first, and how its latest try went."""
    return await service.list_cases(ctx, workflow_id, node_id)


@router.post(
    "/{workflow_id}/steps/{node_id}/evals",
    response_model=EvalCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_step_eval(
    workflow_id: UUID, node_id: UUID, data: EvalCaseCreate, service: WorkflowEvalSvc, ctx: Auth
) -> Any:
    """A case for a step that asks a model: an input, the known output of the steps
    before it, and what its answer should say. A step holds at most 50."""
    return await service.create_case(ctx, workflow_id, node_id, data)


@router.delete("/{workflow_id}/evals/{eval_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_step_eval(
    workflow_id: UUID, eval_id: UUID, service: WorkflowEvalSvc, ctx: Auth
) -> None:
    """Remove a case. Tries already made keep what it said then."""
    await service.delete_case(ctx, workflow_id, eval_id)


@router.post(
    "/{workflow_id}/steps/{node_id}/eval-runs",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_workflow_run)],
)
async def try_step_evals(
    workflow_id: UUID, node_id: UUID, service: WorkflowEvalSvc, ctx: Auth
) -> Any:
    """Start a test run of the step for each case. A case whose run cannot start is
    recorded as refused, with the reason, and the rest still start."""
    return await service.try_cases(ctx, workflow_id, node_id, first_case_charged=True)


@router.get("/{workflow_id}/eval-runs/{eval_run_id}", response_model=EvalRunRead)
async def get_step_eval_run(
    workflow_id: UUID, eval_run_id: UUID, service: WorkflowEvalSvc, ctx: Auth
) -> Any:
    """A try, judged as its runs stand now: each case passed, failed or still going."""
    return await service.get_try(ctx, workflow_id, eval_run_id)
