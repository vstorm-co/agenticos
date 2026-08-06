"""Agent run and approval repositories (PostgreSQL async)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization_secret import OrganizationSecret


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID | None,
    user_id: UUID | None,
    conversation_id: UUID | None,
    surface: str,
    model_label: str | None,
    started_at: datetime,
    exposure_id: UUID | None = None,
    environment_id: UUID | None = None,
    provider: str | None = None,
    secret_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    subagent_task_id: str | None = None,
) -> AgentRun:
    run = AgentRun(
        organization_id=organization_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        user_id=user_id,
        conversation_id=conversation_id,
        exposure_id=exposure_id,
        environment_id=environment_id,
        surface=surface,
        model_label=model_label,
        provider=provider,
        secret_id=secret_id,
        parent_run_id=parent_run_id,
        subagent_task_id=subagent_task_id,
        status=RunStatus.RUNNING.value,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def finish_run(
    db: AsyncSession,
    *,
    run: AgentRun,
    status: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    cost_is_partial: bool,
    ended_at: datetime,
    error: str | None = None,
    logfire_trace_id: str | None = None,
    paused_state: dict[str, Any] | None = None,
) -> AgentRun:
    run.status = status
    run.input_tokens = input_tokens
    run.output_tokens = output_tokens
    run.cost_usd = cost_usd
    run.cost_is_partial = cost_is_partial
    run.ended_at = ended_at
    run.error = error
    # Written on every finish, not only when parking: a run that ended must not
    # keep the state it was parked with, or it can be resumed a second time.
    run.paused_state = paused_state
    if logfire_trace_id is not None:
        run.logfire_trace_id = logfire_trace_id
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def record_delegated_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    organization_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    parent_run_id: UUID,
    subagent_task_id: str,
    user_id: UUID | None,
    conversation_id: UUID | None,
    exposure_id: UUID | None,
    surface: str,
    model_label: str | None,
    provider: str | None,
    secret_id: UUID | None,
    status: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    cost_is_partial: bool,
    started_at: datetime,
    ended_at: datetime,
    error: str | None = None,
) -> AgentRun:
    """Write a delegated run that is already over, in one insert.

    A delegation is reported to the runner *finished*: it has a status, a cost and
    both ends of its window before any row exists. So it is written complete
    rather than opened with `create_run` and closed with `finish_run` - a
    `running` row that no process is running, even for the length of one
    transaction, is a state the run history would have to explain.

    `run_id` is supplied rather than defaulted, because the id is handed to the
    parent's model as the delegation's identity while the run is still going and
    the row is written after it ends. See
    `AgentRunnerService._delegation_recorder` for why the write waits.

    `environment_id` is deliberately absent: that column says which environment
    resolved the version this run answered with, and a delegate's version comes
    from a pin.
    """
    run = AgentRun(
        id=run_id,
        organization_id=organization_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        parent_run_id=parent_run_id,
        subagent_task_id=subagent_task_id,
        user_id=user_id,
        conversation_id=conversation_id,
        exposure_id=exposure_id,
        surface=surface,
        model_label=model_label,
        provider=provider,
        secret_id=secret_id,
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
        started_at=started_at,
        ended_at=ended_at,
        error=error,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def get_run(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> AgentRun | None:
    result = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def claim_parked_run(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> AgentRun | None:
    """Read a run and hold its row for the rest of the transaction.

    Resuming replays a side-effecting tool call, so two requests arriving
    together - a double-clicked Approve - must not both replay it. The second
    waits here and then finds the run no longer parked.
    """
    result = await db.execute(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def mark_running(db: AsyncSession, *, run: AgentRun) -> AgentRun:
    """Take a parked run out of the queue before replaying it."""
    run.status = RunStatus.RUNNING.value
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    include_delegations: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentRun], int]:
    """Run history, newest first, and which kind of row it contains.

    Delegated rows are left out by default, which is the organization's
    question. Every run shares the parent's spend ledger, so a delegation's
    `cost_usd` is already inside its parent's; interleaved, the cost column
    invites a sum that double-counts every delegation, and the count beside it
    disagrees with a month-to-date figure that `sum_cost_since` correctly takes
    only from top-level rows. `total` counts what the page shows.

    `include_delegations` mirrors `sum_cost_since`, and for the same reason: a
    list narrowed to **one agent** is the per-agent question, where a delegate's
    rows are the only record of what it itself did. Without them an agent that
    only ever runs as somebody's delegate has an empty history next to a spend
    figure of forty dollars.

    `parent_run_id` asks the third question, "what did this run delegate", which
    is what `agent_runs_parent_run_id_idx` exists for and takes precedence over
    both: those rows are the delegations of one named run, so a surface can say
    whose they are rather than leaving a reader to guess which of four rows a
    person started.
    """
    query = select(AgentRun).where(AgentRun.organization_id == organization_id)
    count_query = select(func.count(AgentRun.id)).where(AgentRun.organization_id == organization_id)
    if agent_id is not None:
        query = query.where(AgentRun.agent_id == agent_id)
        count_query = count_query.where(AgentRun.agent_id == agent_id)
    if parent_run_id is not None:
        query = query.where(AgentRun.parent_run_id == parent_run_id)
        count_query = count_query.where(AgentRun.parent_run_id == parent_run_id)
    elif not include_delegations:
        query = query.where(AgentRun.parent_run_id.is_(None))
        count_query = count_query.where(AgentRun.parent_run_id.is_(None))

    query = query.order_by(AgentRun.started_at.desc().nullslast()).offset(skip).limit(limit)
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def sum_cost_since(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    agent_id: UUID | None = None,
    include_delegations: bool = False,
) -> Decimal:
    """Total run spend in a window - what a monthly budget is checked against.

    `agent_id` narrows the sum to one agent's runs, because the agent's cap has
    to be measured against the spend it is a cap *on*: checked against the
    organization's total it would be exhausted by the neighbours' runs while
    the agent's own spend stayed invisible in it.

    `include_delegations` decides whether the runs a delegation opened count, and
    the two callers want opposite answers because they are asking different
    questions.

    Left out by default, which is the organization's question - the bill. Every
    run shares one spend ledger, so a delegate's requests are already inside the
    parent run's `cost_usd`; a child row is the same money written down a second
    time, and summing both bills the organization twice for one request. That
    also makes the default the safe one for a caller added later: a total that
    does not double-count.

    Included when the question is one agent's month, because a delegate's rows
    are the only place its own spend is recorded. **Its own**, which for a delegate
    that delegates further means the requests that agent issued and its inline
    specialists' - but not its *published* delegates', because those have rows of
    their own. Every ledger entry carries two attributions: the delegation that made
    it, for the delegation panel, and the nearest agent-row it bills to, for this
    sum. A delegated row is the billed share, so a published delegate's inline
    specialist lands in the delegate's month (agenticos#228) while a published
    grandchild does not (agenticos#180) - the same money is never under one agent's
    month twice, and an inline specialist's spend is never left out of every month.
    A top-level row is still the whole run, descendants included - that is what the
    first question needs. That cap does not stop a run mid-delegation - inside a
    delegation the parent's caps bind, see `app/agents/factory.py` - but it is what
    makes "the researcher agent cost $40 this month" answerable and what a budget
    alert on that agent fires on.
    """
    query = select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(
        AgentRun.organization_id == organization_id,
        AgentRun.started_at >= since,
    )
    if agent_id is not None:
        query = query.where(AgentRun.agent_id == agent_id)
    if not include_delegations:
        query = query.where(AgentRun.parent_run_id.is_(None))
    result = await db.scalar(query)
    return Decimal(result or 0)


async def cost_breakdown(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    include_delegations: bool = False,
) -> list[tuple[UUID, str | None, Decimal, int]]:
    """Spend grouped by agent - the cost dashboard's main query.

    Returns (agent_id, model_label, total_cost, run_count) rows.

    `include_delegations` is the same switch, with the same default and for the
    same reason, as :func:`sum_cost_since`: a delegate's tokens are already inside
    the parent run's `cost_usd`, so counting the child row as well adds money
    nobody was charged. Left out, these rows sum to the organization's bill -
    which is what makes them safe to render beside it, and a breakdown totalling
    more than the total above it is the bug this default exists to stop.

    Passed `True` only where the question is genuinely one agent's - what did the
    researcher cost - because a delegate's rows are the only record of that.
    """
    query = (
        select(
            AgentRun.agent_id,
            AgentRun.model_label,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.started_at >= since,
        )
        .group_by(AgentRun.agent_id, AgentRun.model_label)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    if not include_delegations:
        query = query.where(AgentRun.parent_run_id.is_(None))
    result = await db.execute(query)
    return [(row[0], row[1], Decimal(row[2]), row[3]) for row in result.all()]


async def spend_by_provider(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    include_delegations: bool = False,
) -> list[tuple[str | None, Decimal, int]]:
    """Spend grouped by model provider - "what did we spend at OpenAI".

    Reads the provider recorded *on the run*, not the one its model profile
    points at today: a repointed profile would otherwise rewrite what last
    month appears to have cost. Runs from before this was recorded group under
    NULL, which the caller renders as "not recorded" rather than as a provider.

    `include_delegations` defaults to `False`, as in :func:`sum_cost_since`, and
    this is the grouping where excluding them is least obvious and most necessary.
    A delegation's tokens are already inside the parent run's `cost_usd`, which
    carries the *parent's* provider - so counting the child row too both bills the
    money twice and attributes it to two vendors at once. Excluded, an invoice
    question is answered with numbers that add up to the bill; the price is that a
    delegate running on a second vendor is invisible here, because a run has one
    ledger and one provider column and this table cannot split it.
    """
    query = (
        select(
            AgentRun.provider,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .where(AgentRun.organization_id == organization_id, AgentRun.started_at >= since)
        .group_by(AgentRun.provider)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    if not include_delegations:
        query = query.where(AgentRun.parent_run_id.is_(None))
    result = await db.execute(query)
    return [(row[0], Decimal(row[1]), row[2]) for row in result.all()]


async def spend_by_key(
    db: AsyncSession,
    *,
    organization_id: UUID,
    since: datetime,
    include_delegations: bool = False,
) -> list[tuple[UUID | None, str | None, Decimal, int]]:
    """Spend grouped by the stored key that paid for it.

    Left-joined, so a key deleted after it was used still shows its spend under
    a null label rather than dropping the rows: the money was spent whether or
    not the key still exists.

    `include_delegations` defaults to `False` for the reason :func:`sum_cost_since`
    gives: the delegation's cost is already on the parent's row, under the key that
    row names, so counting both charges one key's spend twice over.
    """
    query = (
        select(
            AgentRun.secret_id,
            OrganizationSecret.name,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.count(AgentRun.id),
        )
        .join(OrganizationSecret, OrganizationSecret.id == AgentRun.secret_id, isouter=True)
        .where(AgentRun.organization_id == organization_id, AgentRun.started_at >= since)
        .group_by(AgentRun.secret_id, OrganizationSecret.name)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    if not include_delegations:
        query = query.where(AgentRun.parent_run_id.is_(None))
    result = await db.execute(query)
    return [(row[0], row[1], Decimal(row[2]), row[3]) for row in result.all()]


async def create_approval(
    db: AsyncSession,
    *,
    approval_id: UUID,
    organization_id: UUID,
    run_id: UUID,
    agent_id: UUID,
    tool_id: str,
    tool_args: dict,
    subagent_name: str | None = None,
    subagent_agent_id: UUID | None = None,
) -> ToolApproval:
    approval = ToolApproval(
        id=approval_id,
        organization_id=organization_id,
        run_id=run_id,
        agent_id=agent_id,
        tool_id=tool_id,
        tool_args=tool_args,
        subagent_name=subagent_name,
        subagent_agent_id=subagent_agent_id,
    )
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return approval


async def get_approval(
    db: AsyncSession, approval_id: UUID, *, organization_id: UUID
) -> ToolApproval | None:
    result = await db.execute(
        select(ToolApproval).where(
            ToolApproval.id == approval_id,
            ToolApproval.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_pending_approvals(
    db: AsyncSession, *, organization_id: UUID, skip: int = 0, limit: int = 50
) -> tuple[list[ToolApproval], int]:
    query = (
        select(ToolApproval)
        .where(
            ToolApproval.organization_id == organization_id,
            ToolApproval.status == ApprovalStatus.PENDING.value,
        )
        .order_by(ToolApproval.created_at.asc())
        .offset(skip)
        .limit(limit)
    )
    count_query = select(func.count(ToolApproval.id)).where(
        ToolApproval.organization_id == organization_id,
        ToolApproval.status == ApprovalStatus.PENDING.value,
    )
    items = list((await db.execute(query)).scalars().all())
    total = (await db.execute(count_query)).scalar() or 0
    return items, total


async def list_approvals_for_run(
    db: AsyncSession, *, run_id: UUID, organization_id: UUID
) -> list[ToolApproval]:
    """Every approval raised by one run, oldest first - what a resume checks."""
    result = await db.execute(
        select(ToolApproval)
        .where(
            ToolApproval.run_id == run_id,
            ToolApproval.organization_id == organization_id,
        )
        .order_by(ToolApproval.created_at.asc())
    )
    return list(result.scalars().all())


async def decide_approval(
    db: AsyncSession,
    *,
    approval: ToolApproval,
    status: str,
    decided_by_user_id: UUID,
    decided_at: datetime,
    note: str | None = None,
) -> ToolApproval:
    approval.status = status
    approval.decided_by_user_id = decided_by_user_id
    approval.decided_at = decided_at
    approval.note = note
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return approval
