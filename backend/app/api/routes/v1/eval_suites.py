"""Eval suite routes - an agent held to a dataset, its triggers and its results.

The per-agent routes carry no role gate and delegate to `EvalSuiteService`,
which resolves access to the agent and the dataset through their grants. Saving
a suite makes the caller its owner, the person its runs spend as.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, EvalSuiteSvc, require
from app.core.permissions import Perm
from app.schemas.eval_suite import (
    EvalSuiteCreate,
    EvalSuiteEstimate,
    EvalSuiteEstimateRequest,
    EvalSuiteList,
    EvalSuiteRead,
    EvalSuiteResultList,
    EvalSuiteResultRead,
    EvalSuiteUpdate,
)

router = APIRouter()


@router.get(
    "/eval-suites",
    response_model=EvalSuiteList,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def list_visible_eval_suites(service: EvalSuiteSvc, ctx: Auth) -> Any:
    """Every suite of the organization on an agent the caller may see."""
    return await service.list_visible(ctx)


@router.get("/agents/{agent_id}/eval-suites", response_model=EvalSuiteList)
async def list_eval_suites(agent_id: UUID, service: EvalSuiteSvc, ctx: Auth) -> Any:
    return await service.list_for_agent(ctx, agent_id)


@router.post("/agents/{agent_id}/eval-suites/estimate", response_model=EvalSuiteEstimate)
async def estimate_eval_suite(
    agent_id: UUID, data: EvalSuiteEstimateRequest, service: EvalSuiteSvc, ctx: Auth
) -> Any:
    """What one run of a suite set up this way costs, and a month of its schedule.

    Writes nothing and calls no model.
    """
    return await service.estimate(ctx, agent_id, data)


@router.post(
    "/agents/{agent_id}/eval-suites",
    response_model=EvalSuiteRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_eval_suite(
    agent_id: UUID, data: EvalSuiteCreate, service: EvalSuiteSvc, ctx: Auth
) -> Any:
    """Set a suite up. It runs as the caller, who must be signed in as themselves."""
    return await service.create(ctx, agent_id, data)


@router.get("/agents/{agent_id}/eval-suites/{suite_id}", response_model=EvalSuiteRead)
async def get_eval_suite(agent_id: UUID, suite_id: UUID, service: EvalSuiteSvc, ctx: Auth) -> Any:
    return await service.get(ctx, agent_id, suite_id)


@router.patch("/agents/{agent_id}/eval-suites/{suite_id}", response_model=EvalSuiteRead)
async def update_eval_suite(
    agent_id: UUID, suite_id: UUID, data: EvalSuiteUpdate, service: EvalSuiteSvc, ctx: Auth
) -> Any:
    """Change, pause or resume a suite. The caller becomes its owner."""
    return await service.update(ctx, agent_id, suite_id, data)


@router.delete(
    "/agents/{agent_id}/eval-suites/{suite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_eval_suite(
    agent_id: UUID, suite_id: UUID, service: EvalSuiteSvc, ctx: Auth
) -> None:
    """Remove a suite and its results. The eval runs it started stay."""
    await service.delete(ctx, agent_id, suite_id)


@router.get("/agents/{agent_id}/eval-suites/{suite_id}/results", response_model=EvalSuiteResultList)
async def list_eval_suite_results(
    agent_id: UUID,
    suite_id: UUID,
    service: EvalSuiteSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> Any:
    """The suite's results, newest first."""
    return await service.results(ctx, agent_id, suite_id, skip=skip, limit=limit)


@router.post(
    "/agents/{agent_id}/eval-suites/{suite_id}/run",
    response_model=EvalSuiteResultRead,
    status_code=status.HTTP_201_CREATED,
)
async def run_eval_suite(agent_id: UUID, suite_id: UUID, service: EvalSuiteSvc, ctx: Auth) -> Any:
    """Run the suite now, as the caller. Refused with 409 while it is paused or running,
    and with 402 when the run would cost more than a budget has left."""
    return await service.run_now(ctx, agent_id, suite_id)
