"""Run history, the approval queue and the cost dashboard.

Three views of the same fact - that an agent did something - from three angles:
what happened (runs), what needs a person (approvals), and what it cost (spend).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import AgentRunnerSvc, ApprovalSvc, Auth, require
from app.core.permissions import Perm
from app.db.models.agent_run import ApprovalStatus, RunStatus, RunSurface
from app.repositories.agent_run import ApprovalFilters, RunFilters, RunOrder, RunRating
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
    took_over_ms: int | None = Query(
        None, ge=0, description="Only runs slower than this. A run still going has no duration"
    ),
    rated: RunRating | None = Query(None, description="Only runs somebody rated this way"),
    order_by: RunOrder = Query(RunOrder.STARTED_AT, description="Sort by start time or duration"),
    descending: bool = Query(True, description="Newest or slowest first"),
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

    `order_by=duration` sorts on `ended_at - started_at`, computed in SQL over
    the whole narrowed set - which is what gets from "p95 is 14.8s" on the
    dashboard to *those runs*. Sorting a page of twenty-five would sort the wrong
    set. Unfinished runs have no duration and sort last in both directions rather
    than as zero.

    `rated=down` is the highest-signal queue here: the answers real people said
    were wrong. A run matches if *anybody* rated a message it produced that way,
    so a run one person liked and another disliked matches both - collapsing that
    into one verdict per run would invent a consensus the rows do not record.

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
            took_over_ms=took_over_ms,
            rated=rated,
        ),
        order_by=order_by,
        descending=descending,
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
    status: Annotated[list[ApprovalStatus] | None, Query()] = None,
    triggered_by_user_id: UUID | None = Query(
        None, description="Only calls parked by runs this person started"
    ),
    created_from: datetime | None = Query(None, description="Parked at or after this instant"),
    created_to: datetime | None = Query(None, description="Parked at or before this instant"),
    oldest_first: bool = Query(True, description="The queue drains from the top"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Tool calls waiting on a human, oldest first - or the record of decisions.

    `status` defaults to pending, which is the queue. Asking for `approved` and
    `rejected` gives the same rows read as an accountability trail: each carries
    the decider and the note, and there is deliberately no way to decide one
    again - a second decision on a decided approval is one of the things this
    platform refuses.

    Oldest first by default, and the default is load-bearing. Nothing expires a
    parked call, so the oldest row can be from months ago; a newest-first queue
    would bury exactly the row somebody needs to see.
    """
    items, total = await service.list_approvals(
        ctx,
        filters=ApprovalFilters(
            statuses=None if not status else [value.value for value in status],
            triggered_by_user_id=triggered_by_user_id,
            created_from=created_from,
            created_to=created_to,
        ),
        oldest_first=oldest_first,
        skip=skip,
        limit=limit,
    )
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
    days: int = Query(30, ge=1, le=365, description="A rolling window. Ignored if `from` is given"),
    from_date: datetime | None = Query(
        None, alias="from", description="Start of an explicit window, instead of `days`"
    ),
    to_date: datetime | None = Query(None, alias="to", description="End of it. Defaults to now"),
) -> Any:
    """Month-to-date spend plus a per-agent breakdown over the chosen window.

    Two ways to say which window, because the page asks for both kinds: `days`
    for the "last N days" presets, `from`/`to` for "this month", "last month" and
    a calendar range. `from` wins when both arrive - an explicit range is a more
    specific request than a default nobody changed.

    **Month-to-date ignores the window entirely**, and every per-agent cap is
    measured against it rather than against the range on screen. A monthly
    ceiling compared with a rolling seven days reads as 20% used on the day the
    cap was actually reached.

    Month-to-date is also calendar-aligned rather than rolling, so the number can
    be reconciled against an invoice.
    """
    since = from_date if from_date is not None else datetime.now(UTC) - timedelta(days=days)
    agents = await service.spend_by_agent(ctx, since=since, until=to_date)
    return CostSummary(
        # Null once a range is explicit: "30 days" beside a `from`/`to` that says
        # otherwise is a second answer to a question already answered.
        period_days=None if from_date is not None else days,
        from_date=since,
        to_date=to_date,
        month_to_date_usd=await service.monthly_spend(ctx),
        # How much of everything below is a fact. Summed from the per-agent rows
        # rather than queried again, so the figure and its breakdown cannot
        # disagree about which runs could not be priced.
        partial_run_count=sum(row.partial_run_count for row in agents),
        by_agent=[
            CostByAgent(
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                cost_usd=row.cost_usd,
                run_count=row.run_count,
                partial_run_count=row.partial_run_count,
                month_to_date_usd=row.month_to_date_usd,
                monthly_cap_usd=row.monthly_cap_usd,
            )
            for row in agents
        ],
        # The two questions an invoice raises, which a per-agent breakdown
        # cannot answer: which vendor was paid, and through which key.
        by_provider=[
            CostByProvider(provider=provider, cost_usd=cost, run_count=runs)
            for provider, cost, runs in await service.spend_by_provider(
                ctx, since=since, until=to_date
            )
        ],
        by_key=[
            CostByKey(secret_id=secret_id, label=label, cost_usd=cost, run_count=runs)
            for secret_id, label, cost, runs in await service.spend_by_key(
                ctx, since=since, until=to_date
            )
        ],
    )
