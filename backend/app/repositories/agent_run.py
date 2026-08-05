"""Agent run and approval repositories (PostgreSQL async)."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User


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
    statuses: Sequence[str] | None = None,
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

    `statuses` narrows to a set of `RunStatus` values and composes with all
    three, on the page and on the count alike. It is a list rather than one
    value because `failed,budget_exceeded` - "what went wrong" - is the query
    somebody actually types, and two requests to ask it would page separately
    and interleave wrongly.
    """
    query = select(AgentRun).where(AgentRun.organization_id == organization_id)
    count_query = select(func.count(AgentRun.id)).where(AgentRun.organization_id == organization_id)
    if agent_id is not None:
        query = query.where(AgentRun.agent_id == agent_id)
        count_query = count_query.where(AgentRun.agent_id == agent_id)
    if statuses is not None:
        query = query.where(AgentRun.status.in_(statuses))
        count_query = count_query.where(AgentRun.status.in_(statuses))
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
    are the only place its own spend is recorded. **Its own**, which is what makes
    summing them meaningful for a delegate that delegates further: a *delegated* row
    holds the requests that agent issued, not the ones its own delegates issued,
    because the ledger those rows are read off stamps every entry with the delegation
    that made it. A row that carried its grandchildren's spend counted the same money
    twice under one agent's month, and did it silently (agenticos#180). A top-level
    row is still the whole run, descendants included - that is what the first
    question needs. That cap does not stop a run mid-delegation - inside a delegation
    the parent's caps bind, see `app/agents/factory.py` - but it is what makes "the
    researcher agent cost $40 this month" answerable and what a budget alert on that
    agent fires on.

    One known gap, agenticos#228: a delegate's *inline* specialist gets no row of its
    own and is no longer inside its delegator's share either, so a delegate that uses
    one under-reports its month by what the specialist spent. The organization's total
    is unaffected - the top-level row is the whole ledger.
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


# -- window aggregates, for GET /stats/usage ----------------------------------
#
# All of these read the same half-open window [start, end) on `started_at` -
# the column the org+started index serves and the one the spend queries already
# filter on. `user_id` narrows to one person's runs, which is the whole of
# scope=own.


def _window_conditions(
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None,
    include_delegations: bool = False,
) -> list[ColumnElement[bool]]:
    """The window every dashboard aggregate shares, delegations out by default.

    `include_delegations` is the switch :func:`sum_cost_since` established, and
    the default is `False` for the reason that made it the default there: a
    delegation's tokens are already inside its parent's row, so counting both
    bills the same run twice. Beyond cost, a delegated row copies its parent's
    `user_id` and `surface`, so including it would also inflate a person's run
    count and invent arrivals on a channel nobody used twice.

    The two aggregates that pass `True` are the two asking about **an agent**
    rather than about the organization - see :func:`runs_by_agent` and
    :func:`usage_by_version`, where a delegate's rows are the only record of
    what the delegate itself did.
    """
    conditions: list[ColumnElement[bool]] = [
        AgentRun.organization_id == organization_id,
        AgentRun.started_at >= start,
        AgentRun.started_at < end,
    ]
    if user_id is not None:
        conditions.append(AgentRun.user_id == user_id)
    if not include_delegations:
        conditions.append(AgentRun.parent_run_id.is_(None))
    return conditions


async def count_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> int:
    """How many runs started in the window."""
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.scalar(select(func.count(AgentRun.id)).where(*conditions))
    return int(result or 0)


async def count_distinct_users(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
) -> int:
    """How many distinct people started a run in the window.

    COUNT(DISTINCT) ignores NULL, so runs with no subject - an embedded
    widget's anonymous visitors - do not count as a person.
    """
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=None
    )
    result = await db.scalar(select(func.count(func.distinct(AgentRun.user_id))).where(*conditions))
    return int(result or 0)


async def latency_percentiles_ms(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> tuple[float | None, float | None]:
    """p50 and p95 of started-to-finished, in milliseconds.

    Only finished runs enter the distribution: `ended_at` is nullable (a
    crashed or parked run has none), and a percentile over half-missing
    durations would be a number with no meaning. No finished runs -> (None,
    None), which the caller must keep distinct from a fast zero.
    """
    duration_ms = func.extract("epoch", AgentRun.ended_at - AgentRun.started_at) * 1000
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.execute(
        select(
            func.percentile_cont(0.5).within_group(duration_ms),
            func.percentile_cont(0.95).within_group(duration_ms),
        ).where(*conditions, AgentRun.ended_at.is_not(None))
    )
    row = result.one()
    p50, p95 = row[0], row[1]
    return (
        float(p50) if p50 is not None else None,
        float(p95) if p95 is not None else None,
    )


async def runs_by_day(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> list[tuple[date, int]]:
    """Sparse (day, count) buckets; the caller zero-fills the window.

    Bucketed in UTC explicitly rather than in the session's timezone, so the
    same row lands on the same day whatever the connection is configured to.
    """
    day = func.date(func.timezone("UTC", AgentRun.started_at))
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.execute(
        select(day, func.count(AgentRun.id)).where(*conditions).group_by(day).order_by(day)
    )
    return [(row[0], row[1]) for row in result.all()]


async def runs_by_dimension(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    dimension: Literal["surface", "status", "model"],
    user_id: UUID | None = None,
) -> list[tuple[str | None, int]]:
    """Run counts grouped by one whitelisted column, largest group first."""
    column = {
        "surface": AgentRun.surface,
        "status": AgentRun.status,
        "model": AgentRun.model_label,
    }[dimension]
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.execute(
        select(column, func.count(AgentRun.id))
        .where(*conditions)
        .group_by(column)
        .order_by(func.count(AgentRun.id).desc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def runs_by_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> list[tuple[UUID, str, int]]:
    """Run counts per agent, with the agent's name, most-used first.

    Inner join on purpose: `agent_id` cascades on delete, so a run without an
    agent does not exist and the join drops nothing.

    **The one composed block that counts delegations**, because it is the only
    one asking about an agent rather than about the organization. The card it
    feeds names every published agent missing from these rows as forgotten and
    offers to archive it; excluded, an agent that runs four hundred times a day
    as somebody's delegate is offered for archiving. A count that does not sum
    to `total_runs` is a documented asymmetry, and that is a false statement.

    So the bars here can exceed the total beside them, and
    :class:`app.schemas.stats.UsageStats` says which block does not sum.
    """
    conditions = _window_conditions(
        organization_id=organization_id,
        start=start,
        end=end,
        user_id=user_id,
        include_delegations=True,
    )
    result = await db.execute(
        select(AgentRun.agent_id, Agent.name, func.count(AgentRun.id))
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(*conditions)
        .group_by(AgentRun.agent_id, Agent.name)
        .order_by(func.count(AgentRun.id).desc())
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


async def sum_cost_window(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> Decimal:
    """Model spend inside the window - the period half of the spend card.

    Distinct from `sum_cost_since`, which is open-ended and feeds budget
    enforcement: a budget is measured against the calendar month, a dashboard
    period against whatever window its filter chose.
    """
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.scalar(
        select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(*conditions)
    )
    return Decimal(result or 0)


async def cost_by_provider_window(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> list[tuple[str | None, Decimal]]:
    """Window spend per provider, as recorded on each run, biggest bill first."""
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    result = await db.execute(
        select(AgentRun.provider, func.coalesce(func.sum(AgentRun.cost_usd), 0))
        .where(*conditions)
        .group_by(AgentRun.provider)
        .order_by(func.coalesce(func.sum(AgentRun.cost_usd), 0).desc())
    )
    return [(row[0], Decimal(row[1])) for row in result.all()]


async def usage_by_version(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
) -> list[tuple[UUID | None, int | None, int, int, float | None, Decimal | None]]:
    """Per-version aggregates for one agent's runs in the window.

    Returns (agent_version_id, version, runs, completed_runs, p95_ms,
    avg_cost_usd) rows, oldest version first. LEFT JOIN because the runs'
    version id SET-NULLs when a version is deleted - the row survives as
    "version deleted", which is the whole reason the column is kept.

    Counts delegations, for the reason `list_runs` gives when narrowed to one
    agent: these are that agent's own runs, and a specialist that only ever
    executes as somebody's delegate would otherwise have nothing to compare
    across versions. `avg_cost_usd` is safe here because it averages one
    agent's rows rather than summing a parent together with its children -
    unless an agent delegates to itself, which nothing in the product does and
    which would show up as one version's average, not as a double bill.
    """
    duration_ms = func.extract("epoch", AgentRun.ended_at - AgentRun.started_at) * 1000
    conditions = _window_conditions(
        organization_id=organization_id,
        start=start,
        end=end,
        user_id=user_id,
        include_delegations=True,
    )
    result = await db.execute(
        select(
            AgentRun.agent_version_id,
            AgentVersion.version,
            func.count(AgentRun.id),
            func.count(AgentRun.id).filter(AgentRun.status == RunStatus.COMPLETED.value),
            func.percentile_cont(0.95)
            .within_group(duration_ms)
            .filter(AgentRun.ended_at.is_not(None)),
            func.avg(AgentRun.cost_usd),
        )
        .join(AgentVersion, AgentVersion.id == AgentRun.agent_version_id, isouter=True)
        .where(*conditions, AgentRun.agent_id == agent_id)
        .group_by(AgentRun.agent_version_id, AgentVersion.version)
        .order_by(AgentVersion.version.asc().nullsfirst())
    )
    return [
        (
            row[0],
            row[1],
            row[2],
            row[3],
            float(row[4]) if row[4] is not None else None,
            Decimal(row[5]) if row[5] is not None else None,
        )
        for row in result.all()
    ]


async def usage_by_user(
    db: AsyncSession,
    *,
    organization_id: UUID,
    start: datetime,
    end: datetime,
    user_id: UUID | None = None,
    limit: int,
) -> list[tuple[UUID, str, str | None, int, Decimal, datetime]]:
    """Per-person aggregates for the window, busiest first.

    Returns (user_id, email, full_name, runs, cost_usd, last_run_at). The
    inner JOIN drops runs with no user behind them - a channel message from
    somebody with no account, or a run whose user was deleted - which is what
    keeps this table consistent with `count_distinct_users`, since SQL's
    COUNT(DISTINCT ...) ignores nulls the same way.

    Ordered by runs, then by email so equal counts do not reshuffle between
    two requests for the same window.
    """
    conditions = _window_conditions(
        organization_id=organization_id, start=start, end=end, user_id=user_id
    )
    runs = func.count(AgentRun.id)
    result = await db.execute(
        select(
            User.id,
            User.email,
            User.full_name,
            runs,
            func.coalesce(func.sum(AgentRun.cost_usd), 0),
            func.max(AgentRun.started_at),
        )
        .join(User, User.id == AgentRun.user_id)
        .where(*conditions)
        .group_by(User.id, User.email, User.full_name)
        .order_by(runs.desc(), User.email.asc())
        .limit(limit)
    )
    return [(row[0], row[1], row[2], row[3], Decimal(row[4]), row[5]) for row in result.all()]


async def count_pending_approval_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> int:
    """The caller's runs currently parked on a pending decision.

    Deliberately not window-bound: this is a queue depth, not a period stat -
    a run parked last month is still stuck today.

    Also deliberately without the delegation filter the window aggregates
    carry. A parked child is a stuck parent, and the card answers "why is my
    agent not finishing"; hiding the row that is actually waiting would answer
    "nothing is". Today it changes nothing, because a delegation is written to
    the database already finished and so never parks - but the day one can,
    this counts it instead of going quietly wrong.
    """
    result = await db.scalar(
        select(func.count(func.distinct(ToolApproval.run_id)))
        .join(AgentRun, AgentRun.id == ToolApproval.run_id)
        .where(
            ToolApproval.organization_id == organization_id,
            ToolApproval.status == ApprovalStatus.PENDING.value,
            AgentRun.user_id == user_id,
        )
    )
    return int(result or 0)


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
