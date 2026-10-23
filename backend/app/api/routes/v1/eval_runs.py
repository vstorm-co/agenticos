"""Eval run routes - an agent answering a dataset, its results and its comparison.

Starting a run is two calls on purpose: `estimate` writes nothing and shows the
spend, and the same body posted to the collection starts it. The per-agent and
per-run routes carry no role gate and delegate to `EvalRunService`, which
resolves access to the agent and the dataset through their grants.
"""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.agents.spec import AgentSpec
from app.api.deps import Auth, EvalRunSvc, require
from app.core.permissions import Perm
from app.schemas.eval_run import (
    EvalCaseList,
    EvalComparisonRead,
    EvalRunEstimate,
    EvalRunList,
    EvalRunRead,
    EvalRunRequest,
)

router = APIRouter()


@router.post("/agents/{agent_id}/eval-runs/estimate", response_model=EvalRunEstimate)
async def estimate_eval_run(
    agent_id: UUID, data: EvalRunRequest, service: EvalRunSvc, ctx: Auth
) -> Any:
    """What the run would cost, and what the agent's and organization's budgets keep after it.

    Writes nothing and calls no model.
    """
    return await service.estimate(ctx, agent_id, data)


@router.post(
    "/agents/{agent_id}/eval-runs",
    response_model=EvalRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def start_eval_run(
    agent_id: UUID, data: EvalRunRequest, service: EvalRunSvc, ctx: Auth
) -> Any:
    """Start the run in the background. Refused with 402, before anything is written,
    when the estimate is more than a budget has left."""
    return await service.start(ctx, agent_id, data)


@router.get("/agents/{agent_id}/eval-runs", response_model=EvalRunList)
async def list_eval_runs(
    agent_id: UUID,
    service: EvalRunSvc,
    ctx: Auth,
    draft: Literal["current", "earlier"] | None = Query(
        None,
        description=(
            "`current`: only the runs that tested the draft as it stands now. `earlier`: "
            "the runs that tested another draft since the latest version was published"
        ),
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """The agent's runs over datasets the caller may read, newest first."""
    return await service.list_for_agent(ctx, agent_id, draft=draft, skip=skip, limit=limit)


@router.get("/datasets/{dataset_id}/eval-runs", response_model=EvalRunList)
async def list_dataset_eval_runs(
    dataset_id: UUID,
    service: EvalRunSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The dataset's runs over agents the caller may see, newest first."""
    return await service.list_for_dataset(ctx, dataset_id, skip=skip, limit=limit)


@router.get(
    "/eval-runs/recent",
    response_model=EvalRunList,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def recent_eval_runs(
    service: EvalRunSvc, ctx: Auth, limit: int = Query(10, ge=1, le=50)
) -> Any:
    """The organization's latest runs the caller may read."""
    return await service.recent(ctx, limit=limit)


@router.get("/eval-runs/{eval_run_id}", response_model=EvalRunRead)
async def get_eval_run(eval_run_id: UUID, service: EvalRunSvc, ctx: Auth) -> Any:
    return await service.get(ctx, eval_run_id)


@router.get("/eval-runs/{eval_run_id}/arms/{arm_id}/spec", response_model=AgentSpec)
async def get_eval_run_arm_spec(
    eval_run_id: UUID, arm_id: UUID, service: EvalRunSvc, ctx: Auth
) -> Any:
    """The spec one side of the run answered with. Needs edit access to the agent."""
    return await service.arm_spec(ctx, eval_run_id, arm_id)


@router.get("/eval-runs/{eval_run_id}/cases", response_model=EvalCaseList)
async def list_eval_run_cases(
    eval_run_id: UUID,
    service: EvalRunSvc,
    ctx: Auth,
    arm_id: UUID | None = Query(None, description="The arm `outcome` is read on"),
    outcome: Literal["passed", "failed", "undecided"] | None = Query(None),
    tag: str | None = Query(None, max_length=100),
    case_id: list[UUID] | None = Query(None, max_length=100, description="Only these cases"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Each case with every attempt every arm made at it."""
    return await service.cases(
        ctx,
        eval_run_id,
        arm_id=arm_id,
        outcome=outcome,
        tag=tag,
        case_ids=case_id,
        skip=skip,
        limit=limit,
    )


@router.get("/eval-runs/{eval_run_id}/comparison", response_model=EvalComparisonRead)
async def compare_eval_run(
    eval_run_id: UUID,
    service: EvalRunSvc,
    ctx: Auth,
    arm_id: UUID | None = Query(None, description="The candidate arm; the first when omitted"),
    baseline_run_id: UUID | None = Query(
        None, description="Compare with this run instead of the default baseline"
    ),
) -> Any:
    """A candidate arm against its baseline: the verdict, the flips and both axes."""
    return await service.compare(ctx, eval_run_id, arm_id=arm_id, baseline_run_id=baseline_run_id)


@router.post("/eval-runs/{eval_run_id}/cancel", response_model=EvalRunRead)
async def cancel_eval_run(eval_run_id: UUID, service: EvalRunSvc, ctx: Auth) -> Any:
    """Stop the run: cases already running finish, no other case starts."""
    return await service.cancel(ctx, eval_run_id)
