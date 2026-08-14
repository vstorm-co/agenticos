"""Run history, the approval queue and the cost dashboard.

Three views of the same fact - that an agent did something - from three angles:
what happened (runs), what needs a person (approvals), and what it cost (spend).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import AgentRunnerSvc, ApprovalSvc, Auth, RunExportSvc, require
from app.api.responses import csv_response
from app.core.permissions import Perm
from app.db.models.agent_run import (
    ApprovalStatus,
    RunOrder,
    RunRating,
    RunStatus,
    RunSurface,
)
from app.repositories.agent_run import ApprovalFilters, RunFilters
from app.schemas.agent import AgentRunResult, ParkedCall, RunStep, SettledCall
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
    RunTranscript,
    RunTranscriptMessage,
)

router = APIRouter()


@router.get("/runs", response_model=AgentRunList, dependencies=[Depends(require(Perm.RUNS_VIEW))])
async def list_runs(
    service: AgentRunnerSvc,
    ctx: Auth,
    agent_id: UUID | None = Query(None),
    status: str | None = Query(
        None, description="Comma-separated run statuses, e.g. failed,budget_exceeded"
    ),
    parent_run_id: UUID | None = Query(
        None, description="List one run's delegations instead of the top level"
    ),
    include_delegations: bool = Query(
        False, description="Include delegated runs - what one agent itself did"
    ),
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
    order_by: RunOrder = Query(
        RunOrder.STARTED_AT, description="Sort by start time, duration, cost or tokens"
    ),
    descending: bool = Query(True, description="Newest, slowest, most expensive or heaviest first"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Runs for the organization, newest first, optionally for one agent.

    Top-level runs only by default - see the service for why a delegated row
    and a run somebody started are never summed down one column.

    `status` takes a set, comma-separated - `?status=failed,budget_exceeded` is
    the "show me the problems" query, and the two are separate statuses precisely
    so that asking for one does not mean asking for the other. An unknown value is
    refused by name rather than ignored, because a filter that silently matches
    nothing looks exactly like an organization with nothing wrong.

    `started_from` and `started_to` are what let the count beside this list be
    reconciled with a spend figure. Without a window the count reads all time
    while the money reads one calendar month, and the obvious comparison between
    the two is wrong by however old the organization is (#198).

    `order_by=duration` sorts on `ended_at - started_at`, computed in SQL over
    the whole narrowed set - which is what gets from "p95 is 14.8s" on the
    dashboard to *those runs*. Sorting a page of twenty-five would sort the wrong
    set. Unfinished runs have no duration and sort last in both directions rather
    than as zero. `order_by=cost` is the same arrangement for money - the most
    expensive runs of the whole narrowed set, not of one page - and
    `order_by=tokens` for context weight, on input and output together.

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
            statuses=RunStatus.parse_csv(status),
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
    down_rated = (
        await service.down_rated_run_ids(ctx, [run.id for run in items]) if items else set()
    )
    return AgentRunList(
        items=[
            AgentRunRead.model_validate(run).model_copy(update={"down_rated": run.id in down_rated})
            for run in items
        ],
        total=total,
    )


@router.get(
    "/runs/export",
    response_model=None,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def export_runs(
    service: RunExportSvc,
    ctx: Auth,
    started_from: datetime | None = Query(None, description="Window start, inclusive. Required"),
    started_to: datetime | None = Query(None, description="Window end, inclusive. Required"),
    agent_id: UUID | None = Query(None),
    status: str | None = Query(None, description="Comma-separated run statuses"),
    parent_run_id: UUID | None = Query(None),
    include_delegations: bool = Query(False),
    surface: RunSurface | None = Query(None),
    user_id: UUID | None = Query(None),
    environment_id: UUID | None = Query(None),
    exposure_id: UUID | None = Query(None),
    agent_version_id: UUID | None = Query(None),
    took_over_ms: int | None = Query(None, ge=0),
    rated: RunRating | None = Query(None),
) -> Any:
    """Run history as CSV, over exactly the rows `GET /runs` would list.

    The same filters as the list route, so the file is what is on screen. Two
    differences the design demands: the date range is **mandatory** here, and a
    match over the row cap is **refused** rather than paged - both because an
    export has no ceiling by nature and so needs one by design. A caller whose
    `runs:view` reaches less than the whole organization exports only their own
    rows, enforced in the query.
    """
    result = await service.export_runs(
        ctx,
        agent_id=agent_id,
        parent_run_id=parent_run_id,
        include_delegations=include_delegations,
        filters=RunFilters(
            statuses=RunStatus.parse_csv(status),
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
    )
    return csv_response(result)


@router.get(
    "/runs/{run_id}", response_model=AgentRunRead, dependencies=[Depends(require(Perm.RUNS_VIEW))]
)
async def get_run(run_id: UUID, service: AgentRunnerSvc, ctx: Auth) -> Any:
    """One run, its trace link, and its neighbours in the agent's history.

    `logfire_url` is on this read and not on the list: resolving it needs the
    version's stored spec, because an agent may redirect its traces to a client's
    own Logfire project, and fifty rows have no use for fifty trace links.
    `prev_run_id`/`next_run_id` ride here for the same reason - a detail view
    walks to its neighbours, a list already is the neighbours.
    """
    run = await service.get_run(ctx, run_id)
    down_rated = await service.down_rated_run_ids(ctx, [run.id])
    prev_run_id, next_run_id = await service.neighbor_run_ids(ctx, run)
    return AgentRunRead.model_validate(run).model_copy(
        update={
            "logfire_url": await service.trace_url(ctx, run),
            "down_rated": run.id in down_rated,
            "prev_run_id": prev_run_id,
            "next_run_id": next_run_id,
        }
    )


@router.get("/runs/{run_id}/transcript", response_model=RunTranscript)
async def get_run_transcript(
    run_id: UUID,
    service: AgentRunnerSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    scope: Literal["run", "conversation"] = Query(
        "run",
        description=(
            "`run` answers the run's own turns; `conversation` answers the whole "
            "thread it sits in, each turn carrying its `run_id` so a client can "
            "still tell which ones are this run's"
        ),
    ),
) -> Any:
    """The turns one run produced, for a run detail view to render as steps.

    `scope=conversation` is the detail view showing the run in context: the whole
    thread, scrolled to the run. It widens nothing - every turn a run writes
    carries its `run_id`, so the thread was already assemblable by iterating its
    runs' transcripts under the same `runs:view`.

    No `require(...)` gate, on purpose: reading a run is authorized rather than
    owned, so the decision belongs to the service, which resolves the run against
    the caller's organization and then checks `runs:view`. A run in another tenant
    reads as absent - the same 404 an id that never existed answers with - so the
    response cannot be used to discover that a run exists. The conversation
    endpoint one route over stays owner-scoped; this does not widen it.

    `conversation_id` is null when the run ran with no conversation, which is how
    the response says "there is no transcript" rather than answering an empty list
    that reads as "the run did nothing".
    """
    run, messages, total = await service.get_run_transcript(
        ctx, run_id, skip=skip, limit=limit, whole_conversation=scope == "conversation"
    )
    ratings = await service.transcript_ratings(ctx, [m.id for m in messages])
    return RunTranscript(
        run_id=run.id,
        conversation_id=run.conversation_id,
        items=[
            RunTranscriptMessage.model_validate(m).model_copy(update=ratings[m.id])
            for m in messages
        ],
        total=total,
    )


@router.get(
    "/runs/{run_id}/parked",
    response_model=list[ParkedCall],
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def get_parked_calls(run_id: UUID, service: AgentRunnerSvc, ctx: Auth) -> Any:
    """What this run is waiting on a decision for, right now.

    The same rows `POST /runs/{run_id}/resume` returns in `parked`, readable
    without resuming anything. A live surface is handed them as a
    `tool_approval_required` frame the moment the run parks, but that frame
    exists only for whoever was watching: reloading the conversation lost the
    panel, and the only way to finish the run was the approvals queue on another
    page (#601). Empty for a run that is not parked - including one whose calls
    were all decided and which is now waiting to be resumed.

    Gated on `approvals:decide` like the resume and the queue, because the rows
    are offered here to be decided.
    """
    run = await service.get_run(ctx, run_id)
    return await service.parked_calls(ctx, run)


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
    segment = await service.resume(ctx, run_id)
    run = segment.run
    return AgentRunResult(
        run_id=run.id,
        output=segment.output,
        status=run.status,
        cost_usd=run.cost_usd,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        # What the continuation actually did. Nothing else carries it: the run
        # executes inside this request rather than on the socket the conversation
        # streams, so a caller given only the answer had to draw the second half
        # of a turn out of nothing.
        steps=[
            RunStep(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                args=call.args,
                result=call.result,
            )
            for call in segment.tool_calls
        ],
        # And what the approved call returned. It belongs to a step the caller
        # drew before the run parked, so it updates that step rather than adding
        # one - the alternative is the same command twice in one turn.
        settled=[
            SettledCall(tool_call_id=tool_call_id, result=result)
            for tool_call_id, result in segment.settled.items()
        ],
        # Empty unless the continuation stopped again, which it does whenever the
        # agent reaches a second gated call. Without it a caller was told the run is
        # still awaiting approval and given nothing to approve.
        parked=await service.parked_calls(ctx, run),
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


@router.get(
    "/approvals/export",
    response_model=None,
    dependencies=[Depends(require(Perm.APPROVALS_DECIDE))],
)
async def export_approvals(
    service: RunExportSvc,
    ctx: Auth,
    created_from: datetime | None = Query(None, description="Parked at or after. Required"),
    created_to: datetime | None = Query(None, description="Parked at or before. Required"),
    status: Annotated[list[ApprovalStatus] | None, Query()] = None,
    triggered_by_user_id: UUID | None = Query(None),
    oldest_first: bool = Query(True),
) -> Any:
    """The approvals record as CSV, over exactly the rows `GET /approvals` lists.

    Gated on `approvals:decide` like the list route - organization-wide, so no
    `Scope.OWN` floor - with the same mandatory-range and row-cap rules the runs
    export has. Absent `status`, the pending queue; asking for `approved` and
    `rejected` is the decided record, decider and note included.
    """
    result = await service.export_approvals(
        ctx,
        filters=ApprovalFilters(
            statuses=None if not status else [value.value for value in status],
            triggered_by_user_id=triggered_by_user_id,
            created_from=created_from,
            created_to=created_to,
        ),
        oldest_first=oldest_first,
    )
    return csv_response(result)


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
        # rather than queried again, so this figure and `by_agent` cannot
        # disagree about which runs could not be priced - they count the same
        # rows. It marks the two breakdowns below without measuring them; see
        # `CostSummary.partial_run_count`.
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


@router.get(
    "/spend/export",
    response_model=None,
    dependencies=[Depends(require(Perm.RUNS_VIEW))],
)
async def export_spend(
    service: RunExportSvc,
    ctx: Auth,
    from_date: datetime | None = Query(None, alias="from", description="Window start. Required"),
    to_date: datetime | None = Query(None, alias="to", description="Window end. Required"),
) -> Any:
    """The per-agent spend breakdown as CSV, over the window on the Spend tab.

    One row per agent - its window share (top-level runs only, so the column sums
    to the bill), the runs behind it and how many could not be priced. The tab's
    month-to-date and cap columns are left off, so every dollar column in the file
    shares one time base. The date range is **mandatory**, unlike `GET /spend`
    where `days` stands in for it, because an export has no default window to fall
    back to. The `Scope.OWN` floor pins the sums to the caller's own runs when it
    binds.
    """
    result = await service.export_spend(ctx, since=from_date, until=to_date)
    return csv_response(result)
