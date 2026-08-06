"""Run history, the approval queue and the cost dashboard.

Three views of the same fact - that an agent did something - from three angles:
what happened (runs), what needs a person (approvals), and what it cost (spend).
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import AgentRunnerSvc, ApprovalSvc, Auth, require
from app.core.permissions import Perm
from app.db.models.agent_run import RunStatus, RunSurface
from app.repositories.agent_run import RunFilters
from app.schemas.agent import AgentRunResult
from app.schemas.agent_run import (
    AgentRunList,
    AgentRunRead,
    ApprovalDecision,
    ApprovalList,
    ApprovalRead,
    CostByAgent,
    CostByKey,
    CostByProvider,
    CostSummary,
)

router = APIRouter()


@router.get("/runs", response_model=AgentRunList, dependencies=[Depends(require(Perm.RUNS_VIEW))])
async def list_runs(
    service: AgentRunnerSvc,
    ctx: Auth,
    agent_id: UUID | None = Query(None),
    parent_run_id: UUID | None = Query(
        None, description="List one run's delegations instead of the top level"
    ),
    include_delegations: bool = Query(
        False, description="Include delegated runs - what one agent itself did"
    ),
    status: Annotated[list[RunStatus] | None, Query()] = None,
    surface: RunSurface | None = Query(None, description="Where the run came from"),
    user_id: UUID | None = Query(None, description="Who the run ran as"),
    started_from: datetime | None = Query(
        None, description="Runs started at or after this instant"
    ),
    started_to: datetime | None = Query(None, description="Runs started at or before this instant"),
    environment_id: UUID | None = Query(
        None, description="Runs on the version this environment pins. Never a delegated run"
    ),
    exposure_id: UUID | None = Query(None, description="Runs admitted through this binding"),
    agent_version_id: UUID | None = Query(None, description="Runs that executed this frozen spec"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Runs for the organization, newest first, optionally for one agent.

    Top-level runs only by default - see the service for why a delegated row
    and a run somebody started are never summed down one column.

    `status` repeats: `?status=failed&status=budget_exceeded` is the "show me the
    problems" query, and the two are separate statuses precisely so that asking
    for one does not mean asking for the other.

    `started_from` and `started_to` are what let the count beside this list be
    reconciled with a spend figure. Without a window the count reads all time
    while the money reads one calendar month, and the obvious comparison between
    the two is wrong by however old the organization is (#198).

    Every filter narrows both the page and `total`, so the number always
    describes the rows under it.
    """
    items, total = await service.list_runs(
        ctx,
        agent_id=agent_id,
        parent_run_id=parent_run_id,
        include_delegations=include_delegations,
        filters=RunFilters(
            statuses=None if not status else [value.value for value in status],
            surface=None if surface is None else surface.value,
            user_id=user_id,
            started_from=started_from,
            started_to=started_to,
            environment_id=environment_id,
            exposure_id=exposure_id,
            agent_version_id=agent_version_id,
        ),
        skip=skip,
        limit=limit,
    )
    return AgentRunList(items=items, total=total)


@router.get(
    "/runs/{run_id}", response_model=AgentRunRead, dependencies=[Depends(require(Perm.RUNS_VIEW))]
)
async def get_run(run_id: UUID, service: AgentRunnerSvc, ctx: Auth) -> Any:
    """One run. The step-by-step trace lives in Logfire under its trace id."""
    return await service.get_run(ctx, run_id)


@router.post(
    "/runs/{run_id}/resume",
    response_model=AgentRunResult,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def resume_run(run_id: UUID, service: AgentRunnerSvc, ctx: Auth) -> Any:
    """Continue a run whose parked tool calls have all been decided.

    Separate from deciding on purpose: a decision is a click and should return
    at once, while continuing the run means executing an agent. Deciding the
    last outstanding call is what makes this call possible, not what performs
    it.
    """
    output, run = await service.resume(ctx, run_id)
    return AgentRunResult(
        run_id=run.id,
        output=output,
        status=run.status,
        cost_usd=run.cost_usd,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
    )


@router.get(
    "/approvals",
    response_model=ApprovalList,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def list_approvals(
    service: ApprovalSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Tool calls waiting on a human, oldest first."""
    items, total = await service.list_pending(ctx, skip=skip, limit=limit)
    return ApprovalList(items=items, total=total)


@router.post(
    "/approvals/{approval_id}",
    response_model=ApprovalRead,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def decide_approval(
    approval_id: UUID, data: ApprovalDecision, service: ApprovalSvc, ctx: Auth
) -> Any:
    """Approve or reject a parked tool call. A decision cannot be revisited."""
    return await service.decide(ctx, approval_id, approved=data.approved, note=data.note)


@router.get("/spend", response_model=CostSummary, dependencies=[Depends(require(Perm.RUNS_VIEW))])
async def get_spend(
    service: AgentRunnerSvc,
    ctx: Auth,
    days: int = Query(30, ge=1, le=365),
) -> Any:
    """Month-to-date spend plus a per-agent breakdown over the chosen window.

    Month-to-date is calendar-aligned rather than rolling, so the number can be
    reconciled against an invoice.
    """
    breakdown = await service.cost_breakdown(ctx, days=days)
    return CostSummary(
        period_days=days,
        month_to_date_usd=await service.monthly_spend(ctx),
        by_agent=[
            CostByAgent(agent_id=agent_id, model_label=model_label, cost_usd=cost, run_count=runs)
            for agent_id, model_label, cost, runs in breakdown
        ],
        # The two questions an invoice raises, which a per-agent breakdown
        # cannot answer: which vendor was paid, and through which key.
        by_provider=[
            CostByProvider(provider=provider, cost_usd=cost, run_count=runs)
            for provider, cost, runs in await service.spend_by_provider(ctx, days=days)
        ],
        by_key=[
            CostByKey(secret_id=secret_id, label=label, cost_usd=cost, run_count=runs)
            for secret_id, label, cost, runs in await service.spend_by_key(ctx, days=days)
        ],
    )
