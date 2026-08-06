"""Agent run and approval repositories (PostgreSQL async)."""

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.conversation import Message
from app.db.models.message_rating import MessageRating
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


class RunRating(enum.StrEnum):
    """Which way a run's answer was rated, as run history asks about it.

    `DOWN` is the reason this exists: `message_ratings` holds a thumb and an
    optional comment per assistant message, and it is the highest-signal
    debugging queue the platform will ever have - the answers real people said
    were wrong, in their own words. Nothing below the app admin could reach any
    of it, which is what makes "quality fell four points" a number nobody can
    act on. `UP` is here because it costs one comparison and "what did people
    like" is the same question from the other side.
    """

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class RunFilters:
    """How run history is narrowed, as one value rather than nine parameters.

    Grouped because these travel together the whole way - a route builds them
    from query parameters, a service passes them through, the repository turns
    each into a `WHERE` - and threading nine optional arguments through three
    layers is how one of them ends up applied to the page and not to the count.
    That is not hypothetical: the count and the list are two queries here, and
    every filter has to reach both or `total` describes a different set from the
    rows under it.

    Attributes:
        statuses: Any of these, not all - `failed` and `budget_exceeded`
            together is the "show me the problems" query, and they are separate
            statuses on purpose.
        surface: Where the run came from.
        user_id: Who it ran as, which is not always who asked - a widget's runs
            carry the widget owner's id, because the visitor is anonymous.
        started_from: Inclusive lower bound on `started_at`.
        started_to: Inclusive upper bound on `started_at`.
        environment_id: Which named environment resolved the version. A
            delegated run never has one - its version comes from a pin - so a
            list narrowed to an environment cannot contain delegations, which is
            why the surface has to say so rather than leave a reader to notice.
        exposure_id: Which binding admitted the run. Null for the dashboard, the
            playground and the API.
        agent_version_id: The frozen spec that answered. The version strip's
            "show me the runs behind this number".
        took_over_ms: Only runs that took longer than this. A run with no
            `ended_at` is excluded rather than treated as zero - it has no
            duration yet, and calling that "fast" is the wrong answer to
            "show me the slow ones".
        rated: Only runs somebody rated that way. `down` is the highest-signal
            queue this platform has - the answers real people said were wrong -
            and until `messages.run_id` existed there was no way to ask a run
            whether it earned one.
    """

    statuses: Sequence[str] | None = None
    surface: str | None = None
    user_id: UUID | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    environment_id: UUID | None = None
    exposure_id: UUID | None = None
    agent_version_id: UUID | None = None
    took_over_ms: int | None = None
    rated: RunRating | None = None

    def conditions(self) -> list[ColumnElement[bool]]:
        """One `WHERE` clause per filter that was actually set.

        Returned as a list rather than applied here, so the same set reaches the
        page query and the count query and cannot diverge between them.
        """
        clauses: list[ColumnElement[bool]] = []
        if self.statuses:
            clauses.append(AgentRun.status.in_(list(self.statuses)))
        if self.surface is not None:
            clauses.append(AgentRun.surface == self.surface)
        if self.user_id is not None:
            clauses.append(AgentRun.user_id == self.user_id)
        if self.started_from is not None:
            clauses.append(AgentRun.started_at >= self.started_from)
        if self.started_to is not None:
            clauses.append(AgentRun.started_at <= self.started_to)
        if self.environment_id is not None:
            clauses.append(AgentRun.environment_id == self.environment_id)
        if self.exposure_id is not None:
            clauses.append(AgentRun.exposure_id == self.exposure_id)
        if self.agent_version_id is not None:
            clauses.append(AgentRun.agent_version_id == self.agent_version_id)
        if self.took_over_ms is not None:
            clauses.append(_duration_ms() > self.took_over_ms)
        if self.rated is not None:
            clauses.append(_was_rated(self.rated))
        return clauses


def _was_rated(rated: RunRating) -> ColumnElement[bool]:
    """Whether anybody rated a message this run produced that way.

    An `EXISTS` rather than a join, so a run whose answer three people disliked
    is one row here and not three - a join would multiply the page and the count
    by however many people happened to press the button.

    "Anybody", deliberately: a run one person liked and another disliked matches
    both filters, because both are true of it. Collapsing that into a single
    verdict per run would be inventing a consensus the rows do not record.

    This is what `messages.run_id` bought. A rating hangs off a message, and
    until a message named its run there was no way to ask a run whether it
    earned one.
    """
    sign = MessageRating.rating > 0 if rated is RunRating.UP else MessageRating.rating < 0
    return (
        select(MessageRating.id)
        .join(Message, Message.id == MessageRating.message_id)
        .where(Message.run_id == AgentRun.id, sign)
        .exists()
    )


def _duration_ms() -> ColumnElement[float]:
    """How long a run took, in milliseconds, computed in SQL.

    In SQL rather than in Python because sorting one page of twenty-five by
    duration is sorting the wrong set: the slowest run in a month is not
    reachable by ordering whichever rows the newest-first page happened to
    return. That is the gap between "p95 is 14.8s" on the dashboard and *those
    runs*.

    Null for a run with no `ended_at` - one still going, or parked on an
    approval. A null is not zero and must not be ordered as one; a still-running
    run's *age* is a different question, and one this column deliberately does
    not answer.
    """
    return func.extract("epoch", AgentRun.ended_at - AgentRun.started_at) * 1000


class RunOrder(enum.StrEnum):
    """What run history is sorted by.

    Two, not an arbitrary column name: an `order_by` built from a query string
    is an injection surface, and these are the two orders the page has a reason
    to offer. Newest-first is the default because run history is read as a feed.
    """

    STARTED_AT = "started_at"
    DURATION = "duration"


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID | None = None,
    parent_run_id: UUID | None = None,
    include_delegations: bool = False,
    filters: RunFilters | None = None,
    order_by: RunOrder = RunOrder.STARTED_AT,
    descending: bool = True,
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

    `filters` narrows both queries by the same conditions - see `RunFilters`,
    which exists so that "narrowed the page but not the count" is not a shape
    this function can be written in. `started_from` is also what makes the count
    reconcilable with a spend figure beside it: without a window, one reads all
    time and the other one calendar month, and the obvious comparison between
    them is wrong by however old the organization is.

    `order_by` sorts in SQL, over the whole narrowed set rather than over a page.
    Both orders put nulls last in both directions, which is a decision rather
    than a default: a run with no `ended_at` has no duration and a run with no
    `started_at` has no place on a timeline, and either of them sorting as zero
    would put unfinished work at the top of "the slowest runs".
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
    for clause in (filters or RunFilters()).conditions():
        query = query.where(clause)
        count_query = count_query.where(clause)

    column = _duration_ms() if order_by is RunOrder.DURATION else AgentRun.started_at
    ordering = column.desc() if descending else column.asc()
    query = query.order_by(ordering.nullslast()).offset(skip).limit(limit)
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


@dataclass(frozen=True)
class ApprovalRow:
    """One row of the approvals queue, with the three names resolved.

    A projection rather than the ORM row, because every field a person actually
    reads on this queue lives in another table: the agent's name in `agents`, who
    triggered the run in `agent_runs`, and who decided in `users`. The alternative
    - relationships on `tool_approvals` plus eager loads - would put lazy-load
    machinery on a table written inside a run for the benefit of one list query.

    The field names match `ApprovalRead` so the schema validates straight from
    this; the duplication is the price of not making the model carry a view's
    shape.

    Attributes:
        agent_name: Whose run this is. `agent_id` names nothing to a reader, and a
            queue of tool ids with no agent is one people approve blind. Not
            optional: both `agent_id` and `run_id` are `ON DELETE CASCADE`, so an
            approval cannot outlive either, and an outer join here would be a
            branch the database makes unreachable.
        triggered_by_user_id: Who started the run. Null for a run nobody started
            as themselves - a widget's visitor is anonymous - and for a run whose
            user has since been deleted, since that column is `SET NULL`.
        triggered_by_email: That person, as something readable.
        decided_by_email: Who decided, for the record view. Null while the call is
            pending, and after a decider's account is deleted - the decision
            outlives the account, which is the point of an audit trail.
    """

    id: UUID
    run_id: UUID
    agent_id: UUID
    agent_name: str
    tool_id: str
    tool_args: dict[str, Any]
    subagent_name: str | None
    subagent_agent_id: UUID | None
    status: str
    triggered_by_user_id: UUID | None
    triggered_by_email: str | None
    decided_by_user_id: UUID | None
    decided_by_email: str | None
    decided_at: datetime | None
    note: str | None
    created_at: datetime | None


@dataclass(frozen=True)
class ApprovalFilters:
    """How the approvals queue is narrowed.

    Attributes:
        statuses: Which decisions to show. The default - pending only - is the
            queue; anything else is the record of what was decided, which is a
            different view of the same rows and deliberately has no buttons.
        triggered_by_user_id: Whose runs. Read off `agent_runs`, not off the
            approval, because an approval belongs to a run and a run belongs to a
            person.
        created_from: Inclusive lower bound on when the call was parked.
        created_to: Inclusive upper bound.
    """

    statuses: Sequence[str] | None = None
    triggered_by_user_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


async def list_approvals(
    db: AsyncSession,
    *,
    organization_id: UUID,
    filters: ApprovalFilters | None = None,
    oldest_first: bool = True,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[ApprovalRow], int]:
    """The approvals queue, or the record of what was decided.

    Oldest first by default, because the queue drains from the top and age is a
    real dimension of it: nothing expires a parked call, so the oldest row can be
    from months ago and pretending otherwise would hide the queue's own problem.

    Both the page and the count are narrowed by the same filters. They are two
    queries, and a filter reaching one and not the other gives a total that
    describes different rows from the page under it.
    """
    narrowing = filters or ApprovalFilters()
    triggered_by = aliased(User)
    decided_by = aliased(User)
    clauses: list[ColumnElement[bool]] = [ToolApproval.organization_id == organization_id]
    clauses.append(
        ToolApproval.status.in_(list(narrowing.statuses))
        if narrowing.statuses
        else ToolApproval.status == ApprovalStatus.PENDING.value
    )
    if narrowing.triggered_by_user_id is not None:
        clauses.append(AgentRun.user_id == narrowing.triggered_by_user_id)
    if narrowing.created_from is not None:
        clauses.append(ToolApproval.created_at >= narrowing.created_from)
    if narrowing.created_to is not None:
        clauses.append(ToolApproval.created_at <= narrowing.created_to)

    ordering = ToolApproval.created_at.asc() if oldest_first else ToolApproval.created_at.desc()
    rows = await db.execute(
        select(
            ToolApproval,
            Agent.name,
            AgentRun.user_id,
            triggered_by.email,
            decided_by.email,
        )
        # Inner for the agent and the run, outer for the two people. Both those
        # foreign keys are `ON DELETE CASCADE`, so an approval cannot outlive
        # either row and an outer join would be defending against a state the
        # database does not allow. The user columns are `SET NULL` and null while
        # a call is still pending, so a decision has to survive its decider's
        # account being deleted - that is what an audit trail is for.
        .join(Agent, Agent.id == ToolApproval.agent_id)
        .join(AgentRun, AgentRun.id == ToolApproval.run_id)
        .outerjoin(triggered_by, triggered_by.id == AgentRun.user_id)
        .outerjoin(decided_by, decided_by.id == ToolApproval.decided_by_user_id)
        .where(*clauses)
        .order_by(ordering)
        .offset(skip)
        .limit(limit)
    )
    items = [
        ApprovalRow(
            id=approval.id,
            run_id=approval.run_id,
            agent_id=approval.agent_id,
            agent_name=agent_name,
            tool_id=approval.tool_id,
            tool_args=approval.tool_args,
            subagent_name=approval.subagent_name,
            subagent_agent_id=approval.subagent_agent_id,
            status=approval.status,
            triggered_by_user_id=run_user_id,
            triggered_by_email=triggered_email,
            decided_by_user_id=approval.decided_by_user_id,
            decided_by_email=decided_email,
            decided_at=approval.decided_at,
            note=approval.note,
            created_at=approval.created_at,
        )
        for approval, agent_name, run_user_id, triggered_email, decided_email in rows.all()
    ]
    count_query = (
        select(func.count(ToolApproval.id))
        .join(AgentRun, AgentRun.id == ToolApproval.run_id)
        .where(*clauses)
    )
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
