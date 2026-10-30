"""Workflow run repository (PostgreSQL async).

Pure data access for the six durable-execution tables. Concurrency-sensitive
writes - claiming an outbox row, inserting one under the live-dispatch unique
index - are plain conditional `UPDATE`/`INSERT` statements here; the compare
and the fallback for a lost race belong to the caller
(`app.services.workflow_execution`), the same split `agent_run_repo.decide_approval`
and its caller already use.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import (
    ColumnElement,
    Interval,
    Select,
    String,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.locks import LockScope, hold_subject
from app.db.models.agent_run import AgentRun, ApprovalStatus, RunStatus, ToolApproval
from app.db.models.background_task_kind import BackgroundTaskKind
from app.db.models.workflow import Workflow
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import (
    DispatchOutbox,
    DispatchOutboxStatus,
    NodeAttempt,
    NodeAttemptStatus,
    NodeRun,
    NodeRunStatus,
    ResourceRef,
    WaitingReason,
    WorkflowEvent,
    WorkflowNodeSpend,
    WorkflowRetainedSpend,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.repositories import workflow as workflow_repo
from app.repositories import workflow_file as workflow_file_repo
from app.schemas.workflow_run import WorkflowRunFilters
from app.worker.jobs import WORKFLOW_DISPATCH_NODE


async def create_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    workflow_version_id: UUID | None,
    draft_graph_snapshot: dict[str, Any] | None,
    mode: str,
    triggered_by: str,
    execution_principal_user_id: UUID | None,
    budget_limit: Decimal | None,
    node_count: int,
    deadline_at: datetime | None,
    root_run_id: UUID | None,
    causation_run_id: UUID | None,
    visited_trigger_ids: list[str],
    depth: int,
    started_at: datetime,
    run_input: dict[str, Any] | None = None,
    reply_conversation_id: UUID | None = None,
    retry_of_run_id: UUID | None = None,
    parent_node_run_id: UUID | None = None,
    timezone: str = "UTC",
    public_origin: bool = False,
    impersonated: bool = False,
    source_artifact_id: UUID | None = None,
    source_version_number: int | None = None,
    execution_api_key_id: UUID | None = None,
    key_scopes: list[str] | None = None,
    inline_result_bytes: int = 0,
) -> WorkflowRun:
    # `root_run_id` is NOT NULL, so it must be known before the first
    # `INSERT` - not filled in after a flush "mints" the id, which never gets
    # that far: the first flush is the INSERT, and it fails the NOT NULL
    # constraint before anything is assigned. Generating the id here, rather
    # than leaving it to the column's own `default=uuid.uuid4`, is what makes
    # it known up front: a root run points at itself.
    run_id = uuid4()
    run = WorkflowRun(
        id=run_id,
        organization_id=organization_id,
        workflow_id=workflow_id,
        workflow_version_id=workflow_version_id,
        draft_graph_snapshot=draft_graph_snapshot,
        mode=mode,
        triggered_by=triggered_by,
        public_origin=public_origin,
        impersonated=impersonated,
        source_artifact_id=source_artifact_id,
        source_version_number=source_version_number,
        execution_principal_user_id=execution_principal_user_id,
        execution_api_key_id=execution_api_key_id,
        key_scopes=key_scopes,
        budget_limit=budget_limit,
        node_count=node_count,
        deadline_at=deadline_at,
        timezone=timezone,
        root_run_id=root_run_id or run_id,
        causation_run_id=causation_run_id,
        visited_trigger_ids=visited_trigger_ids,
        input=run_input or {},
        inline_result_bytes=inline_result_bytes,
        reply_conversation_id=reply_conversation_id,
        retry_of_run_id=retry_of_run_id,
        parent_node_run_id=parent_node_run_id,
        depth=depth,
        started_at=started_at,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def has_external_run_dependents(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID
) -> bool:
    """Cross-workflow run references would prevent the workflow's cascade."""
    source = select(WorkflowRun.id).where(
        WorkflowRun.organization_id == organization_id, WorkflowRun.workflow_id == workflow_id
    )
    source_steps = select(NodeRun.id).where(NodeRun.workflow_run_id.in_(source))
    other = aliased(WorkflowRun)
    reference = (
        select(other.id)
        .where(
            other.workflow_id != workflow_id,
            or_(
                other.root_run_id.in_(source),
                other.causation_run_id.in_(source),
                other.retry_of_run_id.in_(source),
                other.parent_node_run_id.in_(source_steps),
            ),
        )
        .limit(1)
    )
    return await db.scalar(reference) is not None


async def count_runs_in_chain(db: AsyncSession, *, root_run_id: UUID) -> int:
    """How many runs share one root - a chain's size, whatever its shape."""
    total = await db.scalar(
        select(func.count()).select_from(WorkflowRun).where(WorkflowRun.root_run_id == root_run_id)
    )
    return int(total or 0)


async def get_run(db: AsyncSession, run_id: UUID, *, organization_id: UUID) -> WorkflowRun | None:
    result = await db.execute(
        select(WorkflowRun).where(
            WorkflowRun.id == run_id, WorkflowRun.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def run_organization_id(db: AsyncSession, run_id: UUID) -> UUID | None:
    """Tenant metadata for a trusted worker before it takes the run's row lock."""
    return await db.scalar(select(WorkflowRun.organization_id).where(WorkflowRun.id == run_id))


async def inline_result_bytes(db: AsyncSession, organization_id: UUID) -> int:
    """Sum retained inline payload reservations without reading or detoasting JSONB."""
    used = await db.scalar(
        select(func.coalesce(func.sum(WorkflowRun.inline_result_bytes), 0)).where(
            WorkflowRun.organization_id == organization_id
        )
    )
    assert used is not None
    return int(used)


async def get_run_answer(
    db: AsyncSession, run_id: UUID
) -> tuple[str | None, dict[str, Any] | None]:
    """A run's status and its webhook answer, read as columns rather than the
    row, so a caller polling in one session sees each commit rather than the
    row its identity map already holds."""
    result = await db.execute(
        select(WorkflowRun.status, WorkflowRun.webhook_response).where(WorkflowRun.id == run_id)
    )
    row = result.one_or_none()
    return (row.status, row.webhook_response) if row is not None else (None, None)


async def get_run_for_update(
    db: AsyncSession, run_id: UUID, *, organization_id: UUID
) -> WorkflowRun | None:
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_run_by_id_for_update(db: AsyncSession, run_id: UUID) -> WorkflowRun | None:
    """Unscoped, row-locked - for the dispatcher and reconciler, which act on
    ids a trusted internal caller supplies (a job's payload, a sweep's
    own scan), never on a caller-supplied id an organization boundary must
    still be checked against. Every write this makes is still stamped with
    the row's own `organization_id`.

    Every locking read here also sets `populate_existing`: a row this session
    already loaded (a sweep's own scan) would otherwise come back with the
    attributes it had *before* the lock was granted, and a check made on
    those after waiting for the lock would be a check of stale values."""
    result = await db.execute(
        select(WorkflowRun)
        .where(WorkflowRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID | None = None,
    visible_to_user_id: UUID | None = None,
    shared_workflow_ids: list[UUID] | None = None,
    filters: WorkflowRunFilters | None = None,
    public_only: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkflowRun], int]:
    """Runs in `organization_id`, optionally narrowed to one workflow and by `filters`.

    Without `workflow_id`, a `visible_to_user_id` narrows the list to runs of
    the workflows that user may see - their own, organization-visible ones
    and `shared_workflow_ids` - by the same condition the workflow listing
    uses (`workflow_repo.visible_to`). `None` means the caller's role already
    reaches every workflow.
    """
    where = [WorkflowRun.organization_id == organization_id]
    if public_only:
        where.append(WorkflowRun.public_origin.is_(True))
    if filters is not None:
        if filters.statuses:
            where.append(WorkflowRun.status.in_([item.value for item in filters.statuses]))
        if filters.mode is not None:
            where.append(WorkflowRun.mode == filters.mode.value)
        if filters.triggered_by is not None:
            where.append(WorkflowRun.triggered_by == filters.triggered_by.value)
        if filters.created_after is not None:
            where.append(WorkflowRun.created_at >= filters.created_after)
        if filters.created_before is not None:
            where.append(WorkflowRun.created_at < filters.created_before)
    if workflow_id is not None:
        where.append(WorkflowRun.workflow_id == workflow_id)
    elif visible_to_user_id is not None:
        visible = select(Workflow.id).where(
            Workflow.organization_id == organization_id,
            workflow_repo.visible_to(
                user_id=visible_to_user_id, shared_ids=shared_workflow_ids or []
            ),
        )
        where.append(WorkflowRun.workflow_id.in_(visible))
    total = await db.scalar(select(func.count()).select_from(WorkflowRun).where(*where)) or 0
    result = await db.execute(
        select(WorkflowRun)
        .where(*where)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def update_run(
    db: AsyncSession, *, run: WorkflowRun, update_data: dict[str, Any]
) -> WorkflowRun:
    for field, value in update_data.items():
        setattr(run, field, value)
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


async def create_node_run(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    node_instance_id: UUID,
    scope_path: list[dict[str, Any]],
    skipped_at: datetime | None = None,
) -> NodeRun:
    """A `NodeRun` for one node in one scope - `pending`, or `skipped` when
    `skipped_at` says when the dispatcher found it unreachable."""
    node_run = NodeRun(
        organization_id=organization_id,
        workflow_run_id=workflow_run_id,
        node_instance_id=node_instance_id,
        scope_path=scope_path,
    )
    if skipped_at is not None:
        node_run.status = NodeRunStatus.SKIPPED.value
        node_run.ended_at = skipped_at
    db.add(node_run)
    await db.flush()
    await db.refresh(node_run)
    return node_run


# A run's node work is outstanding while it is still scheduling. Summing
# `node_count` over these - not counting materialized `node_runs` - is what makes
# the admission reservation durable: a wide graph holds its whole count the moment
# it is admitted, long before its downstream nodes exist.
#
# `needs_attention` is not in this set though it is not terminal: it is a dead end a
# person resolves by retrying or cancelling, so a run parked there will not schedule
# the rest of its graph, and charging its whole `node_count` for ever would let a few
# stuck wide runs exhaust the quota and 429 every later start until each is
# resolved by hand. It holds quota only while it still has live node work: a step
# of it executing (an `in_flight` attempt) or a claimed dispatch row - a sibling
# branch that is still finishing. A dispatch row that is only `pending` is not held
# work: nothing is executing, and a person is not waiting on a worker. `_holds_quota`
# is the whole rule.
_LIVE_RUN_STATUSES = tuple(
    status.value
    for status in WorkflowRunStatus
    if not status.is_terminal and status is not WorkflowRunStatus.NEEDS_ATTENTION
)

# A step of the run executes, or a worker holds a step's dispatch row.
_HAS_LIVE_NODE_WORK = or_(
    exists().where(
        NodeAttempt.node_run_id == NodeRun.id,
        NodeRun.workflow_run_id == WorkflowRun.id,
        NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value,
    ),
    exists().where(
        DispatchOutbox.workflow_run_id == WorkflowRun.id,
        DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
    ),
)


def _holds_quota() -> ColumnElement[bool]:
    """Whether a run still reserves node work: live status, or needing attention with work in hand."""
    return or_(
        WorkflowRun.status.in_(_LIVE_RUN_STATUSES),
        and_(
            WorkflowRun.status == WorkflowRunStatus.NEEDS_ATTENTION.value,
            _HAS_LIVE_NODE_WORK,
        ),
    )


async def count_unfinished_runs(
    db: AsyncSession, *, workflow_id: UUID, organization_id: UUID
) -> int:
    """The workflow's runs that have not ended, one waiting for a person included."""
    terminal = [status.value for status in WorkflowRunStatus if status.is_terminal]
    stmt = select(func.count()).where(
        WorkflowRun.workflow_id == workflow_id,
        WorkflowRun.organization_id == organization_id,
        WorkflowRun.status.not_in(terminal),
    )
    return (await db.execute(stmt)).scalar_one()


# Advisory-lock classes for workflow admission (#1907). Transaction-scoped
# advisory locks, not row locks: the admission check reads an aggregate and then
# inserts a *new* run, so there is no existing row to lock, and two concurrent
# starts would otherwise both read the same sum before either committed. The org
# ceiling and the (cross-organization) principal ceiling need separate locks,
# taken in a fixed order - org before principal - so concurrent starts that share
# either dimension cannot deadlock.
_ORG_ADMISSION_LOCK_NAMESPACE = 1907
_PRINCIPAL_ADMISSION_LOCK_NAMESPACE = 1970


async def lock_admission(
    db: AsyncSession, *, organization_id: UUID, principal_user_id: UUID | None
) -> None:
    """Serialize run admission until this transaction ends.

    Taken before the reservation sums are read and held to commit - by which
    point this start's run row exists - so concurrent starts queue through the
    check one at a time and neither ceiling can be overshot by racing reads. The
    organization lock covers the org ceiling; the principal lock covers the
    principal ceiling, which is counted across *every* organization (a caller who
    can create organizations must not multiply their allowance by spreading runs
    across them). Always org first, then principal, so the order is global.
    """
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                _ORG_ADMISSION_LOCK_NAMESPACE, func.hashtext(str(organization_id))
            )
        )
    )
    if principal_user_id is not None:
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    _PRINCIPAL_ADMISSION_LOCK_NAMESPACE, func.hashtext(str(principal_user_id))
                )
            )
        )


async def count_live_runs(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, mode: str
) -> int:
    """How many of one workflow's runs in `mode` are still under way."""
    return int(
        await db.scalar(
            select(func.count()).where(
                WorkflowRun.organization_id == organization_id,
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.mode == mode,
                _holds_quota(),
            )
        )
        or 0
    )


async def count_live_runs_with_status(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    mode: str,
    statuses: Sequence[WorkflowRunStatus],
) -> int:
    """How many of one workflow's runs in `mode` that hold quota are in one of `statuses`."""
    return int(
        await db.scalar(
            select(func.count()).where(
                WorkflowRun.organization_id == organization_id,
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.mode == mode,
                WorkflowRun.status.in_([status.value for status in statuses]),
                _holds_quota(),
            )
        )
        or 0
    )


async def spent_since(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, since: datetime
) -> Decimal:
    """Spend admitted since `since`, including content-free retained accounting.

    Both sums share one statement snapshot: a retention transaction moves a fee
    between the two tables atomically, so admission never sees it twice or loses it.
    """
    live = (
        select(func.coalesce(func.sum(WorkflowRun.spent_cost + WorkflowRun.child_cost), 0))
        .where(
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.workflow_id == workflow_id,
            WorkflowRun.created_at >= since,
        )
        .scalar_subquery()
    )
    retained = (
        select(func.coalesce(func.sum(WorkflowRetainedSpend.cost_usd), 0))
        .where(
            WorkflowRetainedSpend.organization_id == organization_id,
            WorkflowRetainedSpend.workflow_id == workflow_id,
            WorkflowRetainedSpend.admitted_at >= since,
        )
        .scalar_subquery()
    )
    return Decimal(await db.scalar(select(live + retained)) or 0)


async def run_figures(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, since: datetime
) -> dict[str, Any]:
    """One workflow's real runs since `since`: how many ended each way, their spend,
    and how long the ones that ended took at the median and the 95th percentile."""
    real = (
        WorkflowRun.organization_id == organization_id,
        WorkflowRun.workflow_id == workflow_id,
        WorkflowRun.mode == "real",
        WorkflowRun.created_at >= since,
    )
    counts = {
        row.status: (int(row.runs), Decimal(row.cost), bool(row.partial))
        for row in (
            await db.execute(
                select(
                    WorkflowRun.status,
                    func.count().label("runs"),
                    func.coalesce(
                        func.sum(WorkflowRun.spent_cost + WorkflowRun.child_cost), 0
                    ).label("cost"),
                    func.coalesce(func.bool_or(WorkflowRun.cost_is_partial), False).label(
                        "partial"
                    ),
                )
                .where(*real)
                .group_by(WorkflowRun.status)
            )
        ).all()
    }
    took = func.extract("epoch", WorkflowRun.ended_at - WorkflowRun.started_at)
    p50, p95 = (
        await db.execute(
            select(
                func.percentile_cont(0.5).within_group(took),
                func.percentile_cont(0.95).within_group(took),
            ).where(*real, WorkflowRun.started_at.is_not(None), WorkflowRun.ended_at.is_not(None))
        )
    ).one()
    return {
        "counts": counts,
        "p50": None if p50 is None else float(p50),
        "p95": None if p95 is None else float(p95),
    }


async def runs_by_day(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, since: datetime
) -> list[Any]:
    """One workflow's real runs since `since`, counted by UTC day and status."""
    day = func.date(func.timezone("UTC", WorkflowRun.created_at)).label("day")
    return list(
        (
            await db.execute(
                select(
                    day,
                    WorkflowRun.status,
                    func.count().label("runs"),
                    func.coalesce(
                        func.sum(WorkflowRun.spent_cost + WorkflowRun.child_cost), 0
                    ).label("cost"),
                )
                .where(
                    WorkflowRun.organization_id == organization_id,
                    WorkflowRun.workflow_id == workflow_id,
                    WorkflowRun.mode == "real",
                    WorkflowRun.created_at >= since,
                )
                .group_by(day, WorkflowRun.status)
            )
        ).all()
    )


async def step_figures(
    db: AsyncSession, *, organization_id: UUID, workflow_id: UUID, since: datetime
) -> list[Any]:
    """Each step's node runs in one workflow's real runs since `since`: how many,
    how many failed, what their attempts spent and how long one took on average."""
    attempt_cost = (
        select(func.coalesce(func.sum(NodeAttempt.cost), 0))
        .where(NodeAttempt.node_run_id == NodeRun.id)
        .scalar_subquery()
    )
    called = aliased(WorkflowRun)
    called_cost = (
        select(func.coalesce(func.sum(called.spent_cost + called.child_cost), 0))
        .where(called.parent_node_run_id == NodeRun.id, called.organization_id == organization_id)
        .correlate(NodeRun)
        .scalar_subquery()
    )
    took = func.extract("epoch", NodeRun.ended_at - NodeRun.started_at)
    return list(
        (
            await db.execute(
                select(
                    NodeRun.node_instance_id,
                    func.count().label("runs"),
                    func.count().filter(NodeRun.status == "failed").label("failed"),
                    func.coalesce(func.sum(attempt_cost + called_cost), 0).label("cost"),
                    func.avg(took).label("avg_seconds"),
                )
                .join(WorkflowRun, WorkflowRun.id == NodeRun.workflow_run_id)
                .where(
                    WorkflowRun.organization_id == organization_id,
                    WorkflowRun.workflow_id == workflow_id,
                    WorkflowRun.mode == "real",
                    WorkflowRun.created_at >= since,
                )
                .group_by(NodeRun.node_instance_id)
            )
        ).all()
    )


def _visible_workflows(
    *, organization_id: UUID, user_id: UUID, see_all: bool, shared_ids: list[UUID]
) -> Select[UUID]:
    query = select(Workflow.id).where(Workflow.organization_id == organization_id)
    if not see_all:
        query = query.where(workflow_repo.visible_to(user_id=user_id, shared_ids=shared_ids))
    return query


class WorkflowRunSummary(NamedTuple):
    workflow_id: UUID
    name: str
    status: str
    runs: int
    cost: Decimal


async def runs_by_workflow(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    see_all: bool,
    shared_ids: list[UUID],
    since: datetime,
    until: datetime,
) -> list[WorkflowRunSummary]:
    """Every visible workflow's real runs in `[since, until)`, grouped in SQL."""
    visible = _visible_workflows(
        organization_id=organization_id, user_id=user_id, see_all=see_all, shared_ids=shared_ids
    )
    result = await db.execute(
        select(
            WorkflowRun.workflow_id,
            Workflow.name,
            WorkflowRun.status,
            func.count(),
            func.coalesce(func.sum(WorkflowRun.spent_cost), 0),
        )
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.workflow_id.in_(visible),
            WorkflowRun.mode == "real",
            WorkflowRun.created_at >= since,
            WorkflowRun.created_at < until,
        )
        .group_by(WorkflowRun.workflow_id, Workflow.name, WorkflowRun.status)
    )
    return [
        WorkflowRunSummary(identifier, name, status, int(count), Decimal(cost))
        for identifier, name, status, count, cost in result.all()
    ]


async def count_waiting_on_people(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, see_all: bool, shared_ids: list[UUID]
) -> int:
    """All visible workflows' real runs currently waiting for a person.

    A run is counted once, by its derived status (`run_status.derive_status`): an approval
    wait beside a branch that is still running is one run waiting for approval.
    """
    visible = _visible_workflows(
        organization_id=organization_id, user_id=user_id, see_all=see_all, shared_ids=shared_ids
    )
    count = await db.scalar(
        select(func.count()).where(
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.workflow_id.in_(visible),
            WorkflowRun.mode == "real",
            WorkflowRun.status.in_(
                (WorkflowRunStatus.WAITING_APPROVAL.value, WorkflowRunStatus.NEEDS_ATTENTION.value)
            ),
        )
    )
    return int(count or 0)


async def sum_reserved_node_work(
    db: AsyncSession,
    *,
    organization_id: UUID | None = None,
    principal_user_id: UUID | None = None,
) -> int:
    """The graph node work live runs still hold in reserve, scoped by the filters.

    The sum of `node_count` over every live run matching the filters - each run's
    whole worst-case node work, counted from the instant it is admitted and
    released when it ends, whether or not its nodes have materialized yet. With
    `organization_id`, the organization ceiling reads it org-scoped (via
    `ix_workflow_run_org_status`). With `principal_user_id` and no organization,
    the principal ceiling reads it across every organization, so a caller who can
    create organizations cannot get a fresh allowance in each.
    """
    stmt = select(func.coalesce(func.sum(WorkflowRun.node_count), 0)).where(_holds_quota())
    if organization_id is not None:
        stmt = stmt.where(WorkflowRun.organization_id == organization_id)
    if principal_user_id is not None:
        stmt = stmt.where(WorkflowRun.execution_principal_user_id == principal_user_id)
    return int(await db.scalar(stmt) or 0)


async def get_node_run_by_id(db: AsyncSession, node_run_id: UUID) -> NodeRun | None:
    """Unscoped - see `get_run_by_id_for_update` for why the reconciler needs this."""
    result = await db.execute(select(NodeRun).where(NodeRun.id == node_run_id))
    return result.scalar_one_or_none()


async def get_node_run_by_id_for_update(db: AsyncSession, node_run_id: UUID) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun)
        .where(NodeRun.id == node_run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_node_run_by_identity(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    node_instance_id: UUID,
    scope_path: list[dict[str, Any]],
) -> NodeRun | None:
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeRun.node_instance_id == node_instance_id,
            NodeRun.scope_path == scope_path,
        )
    )
    return result.scalar_one_or_none()


async def list_node_run_statuses(db: AsyncSession, *, workflow_run_id: UUID) -> list[str]:
    """The status of every top-level `NodeRun` of a run - what deciding "has it
    finished" reads. A loop body's rows are its loop's to account for."""
    result = await db.execute(
        select(NodeRun.status).where(
            NodeRun.workflow_run_id == workflow_run_id, NodeRun.scope_path == []
        )
    )
    return list(result.scalars().all())


async def list_node_runs_at(
    db: AsyncSession, *, workflow_run_id: UUID, scope_path: list[dict[str, Any]]
) -> list[NodeRun]:
    """Every `NodeRun` of one loop iteration (or of the top level, for `[]`)."""
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.workflow_run_id == workflow_run_id, NodeRun.scope_path == scope_path
        )
    )
    return list(result.scalars().all())


async def list_node_runs_of(
    db: AsyncSession, *, workflow_run_id: UUID, node_instance_ids: Sequence[UUID]
) -> list[NodeRun]:
    """Every `NodeRun` of the named nodes, in every loop iteration."""
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeRun.node_instance_id.in_(node_instance_ids),
        )
    )
    return list(result.scalars().all())


async def list_node_runs_page(
    db: AsyncSession, *, workflow_run_id: UUID, organization_id: UUID, skip: int, limit: int
) -> tuple[list[NodeRun], int]:
    """A page of a run's node runs, in the order they were created, and how many there are."""
    where = [NodeRun.workflow_run_id == workflow_run_id, NodeRun.organization_id == organization_id]
    total = await db.scalar(select(func.count()).select_from(NodeRun).where(*where)) or 0
    result = await db.execute(
        select(NodeRun)
        .where(*where)
        .order_by(NodeRun.created_at, NodeRun.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def list_attempts_of(db: AsyncSession, *, node_run_ids: Sequence[UUID]) -> list[NodeAttempt]:
    """Every attempt of the named node runs, oldest first per node run."""
    if not node_run_ids:
        return []
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.node_run_id.in_(node_run_ids))
        .order_by(NodeAttempt.attempt_no)
    )
    return list(result.scalars().all())


async def list_live_node_runs(db: AsyncSession, *, workflow_run_id: UUID) -> list[NodeRun]:
    """A run's `NodeRun`s not yet ended - what ending the run has to close.

    A step needing attention is open work too: nothing will resolve it once the run ends.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeRun.status.in_(
                [
                    NodeRunStatus.PENDING.value,
                    NodeRunStatus.RUNNING.value,
                    NodeRunStatus.WAITING.value,
                    NodeRunStatus.NEEDS_ATTENTION.value,
                ]
            ),
        )
    )
    return list(result.scalars().all())


LiveNodeState = tuple[NodeRunStatus, WaitingReason | None]
"""A live step's status and, if it waits, what for - all a run's derived status reads."""


async def list_live_node_states(db: AsyncSession, *, workflow_run_id: UUID) -> list[LiveNodeState]:
    """The status and wait reason of every live step of a run, needing attention included."""
    result = await db.execute(
        select(NodeRun.status, NodeRun.waiting_reason).where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeRun.status.in_(
                [
                    NodeRunStatus.PENDING.value,
                    NodeRunStatus.RUNNING.value,
                    NodeRunStatus.WAITING.value,
                    NodeRunStatus.NEEDS_ATTENTION.value,
                ]
            ),
        )
    )
    return [
        (NodeRunStatus(status), None if reason is None else WaitingReason(reason))
        for status, reason in result.all()
    ]


async def count_node_runs(db: AsyncSession, *, workflow_run_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(NodeRun)
            .where(NodeRun.workflow_run_id == workflow_run_id)
        )
        or 0
    )


async def find_node_run_waiting_on_agent_run(
    db: AsyncSession, agent_run_id: UUID, *, organization_id: UUID
) -> NodeRun | None:
    """The `NodeRun` still parked on this agent run, if any - the approval wake-up needs it.

    Only a `waiting` node counts: the link can outlive the wait on a row
    written before it was cleared on the way out, and a node that already
    moved on must not be woken, nor collide with the one that is parked.
    """
    result = await db.execute(
        select(NodeRun)
        .where(
            NodeRun.waiting_agent_run_id == agent_run_id,
            NodeRun.organization_id == organization_id,
            NodeRun.status == NodeRunStatus.WAITING.value,
        )
        .order_by(NodeRun.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_stale_approval_waits(db: AsyncSession, *, limit: int = 100) -> list[NodeRun]:
    """`NodeRun`s parked on an approval every blocking decision has already answered.

    The reconciler's backstop for the direct wake `ApprovalService.decide`
    queues via `spawn_after_commit`: if that trigger is lost, this finds the
    same shape from the data alone.

    "Already answered" is read off `tool_approvals` directly - no row still
    `pending` for the parked `agent_runs` id - rather than off
    `agent_runs.status`: `ApprovalService.decide` only ever writes the
    `ToolApproval` row (`agent_runs.paused_state`/`status` stay exactly as
    `AgentRunnerService.resume` itself changes them, per this design's own
    "recorded exactly where it is today"), so `agent_runs.status` never
    actually leaves `awaiting_approval` until *something* calls `resume` -
    which is precisely the trigger this function exists to substitute for
    when it is lost. `AgentRunnerService._decisions` requires the identical
    "nothing still pending" condition before it will replay a park, so this
    mirrors the one check that already decides whether a resume can proceed.

    An agent run that is `running` is skipped: somebody is resuming it, and
    the node is found once it ends. Any other status counts, including one
    that ended without ever being resumed (an expired approval cancels it) -
    the node must wake so its handler can see that outcome and fail, rather
    than stay parked on an agent run nothing will ever resume.

    A *workflow* run cancelled out from under this wait is a separate case -
    `cancel()` leaves a waiting `NodeRun` and its linked `agent_runs` row
    exactly as they were (documented gap: `WorkflowExecutionService.cancel`),
    so the checks above stay true for ever and this would otherwise re-insert
    an outbox row on every sweep, for `begin_attempt` to close again as soon
    as it sees the terminal run. Excluding a terminal owning `WorkflowRun`
    here is what stops that.
    """
    live_outbox = (
        select(DispatchOutbox.node_run_id)
        .where(
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            )
        )
        .distinct()
    )
    still_pending = (
        select(ToolApproval.id)
        .where(
            ToolApproval.run_id == AgentRun.id,
            ToolApproval.status == ApprovalStatus.PENDING.value,
        )
        .exists()
    )
    terminal_statuses = [status.value for status in WorkflowRunStatus if status.is_terminal]
    result = await db.execute(
        select(NodeRun)
        .join(
            AgentRun,
            (AgentRun.id == NodeRun.waiting_agent_run_id)
            & (AgentRun.organization_id == NodeRun.organization_id),
        )
        .join(WorkflowRun, WorkflowRun.id == NodeRun.workflow_run_id)
        .where(
            NodeRun.status == NodeRunStatus.WAITING.value,
            NodeRun.waiting_reason == WaitingReason.APPROVAL.value,
            NodeRun.waiting_agent_run_id.is_not(None),
            AgentRun.status != RunStatus.RUNNING.value,
            WorkflowRun.status.not_in(terminal_statuses),
            ~still_pending,
            NodeRun.id.not_in(live_outbox),
        )
        # By run id, for the same lock-order reason as `list_orphaned_in_flight`.
        .order_by(NodeRun.workflow_run_id, NodeRun.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_node_run(
    db: AsyncSession, *, node_run: NodeRun, update_data: dict[str, Any]
) -> NodeRun:
    for field, value in update_data.items():
        setattr(node_run, field, value)
    db.add(node_run)
    await db.flush()
    await db.refresh(node_run)
    return node_run


async def create_attempt(
    db: AsyncSession,
    *,
    organization_id: UUID,
    node_run_id: UUID,
    attempt_no: int,
    idempotency_key: str,
    retry_guarantee: str | None,
    started_at: datetime,
    reserved_usd: Decimal | None = None,
) -> NodeAttempt:
    attempt = NodeAttempt(
        organization_id=organization_id,
        node_run_id=node_run_id,
        attempt_no=attempt_no,
        idempotency_key=idempotency_key,
        retry_guarantee=retry_guarantee,
        reserved_usd=reserved_usd,
        status=NodeAttemptStatus.IN_FLIGHT.value,
        started_at=started_at,
    )
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def get_attempt(db: AsyncSession, attempt_id: UUID) -> NodeAttempt | None:
    """Always re-read from the database: callers read it under the owning run's
    lock to decide whether the attempt is still `in_flight`."""
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.id == attempt_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def call_history_requires_child(
    db: AsyncSession, *, organization_id: UUID, node_run_id: UUID
) -> bool:
    """Whether any attempt completed a call or left its admission uncertain.

    A later permission refusal must not hide an earlier wait. Query only an
    existence flag, without loading potentially large historical result bodies.
    """
    return bool(
        await db.scalar(
            select(
                exists().where(
                    NodeAttempt.organization_id == organization_id,
                    NodeAttempt.node_run_id == node_run_id,
                    or_(
                        NodeAttempt.status.in_(
                            [
                                NodeAttemptStatus.COMPLETED.value,
                                NodeAttemptStatus.IN_FLIGHT.value,
                                NodeAttemptStatus.UNCERTAIN.value,
                            ]
                        ),
                        NodeAttempt.result["error"]["code"].as_string() == "CALLED_WORKFLOW_FAILED",
                    ),
                )
            )
        )
    )


async def get_latest_attempt(db: AsyncSession, *, node_run_id: UUID) -> NodeAttempt | None:
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.node_run_id == node_run_id)
        .order_by(NodeAttempt.attempt_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_attempts(
    db: AsyncSession, *, node_run_ids: Sequence[UUID]
) -> dict[UUID, NodeAttempt]:
    """The latest attempt of each named node run, keyed by node run."""
    if not node_run_ids:
        return {}
    result = await db.execute(
        select(NodeAttempt)
        .where(NodeAttempt.node_run_id.in_(node_run_ids))
        .order_by(NodeAttempt.node_run_id, NodeAttempt.attempt_no.desc())
        .distinct(NodeAttempt.node_run_id)
    )
    return {attempt.node_run_id: attempt for attempt in result.scalars().all()}


async def latest_attempt_result_bytes(db: AsyncSession, *, node_run_ids: Sequence[UUID]) -> int:
    """Measure latest results as decoded JSON text without sending their bodies to Python."""
    if not node_run_ids:
        return 0
    latest = (
        select(func.coalesce(func.octet_length(cast(NodeAttempt.result, String)), 0).label("bytes"))
        .where(NodeAttempt.node_run_id.in_(node_run_ids))
        .order_by(NodeAttempt.node_run_id, NodeAttempt.attempt_no.desc())
        .distinct(NodeAttempt.node_run_id)
        .subquery()
    )
    return int(await db.scalar(select(func.coalesce(func.sum(latest.c.bytes), 0))) or 0)


async def settle_attempt(
    db: AsyncSession,
    *,
    attempt: NodeAttempt,
    status: str,
    result: dict[str, Any] | None,
    cost: Decimal,
    cost_is_partial: bool,
    ended_at: datetime,
) -> NodeAttempt:
    attempt.status = status
    attempt.result = result
    attempt.cost = cost
    attempt.cost_is_partial = cost_is_partial
    attempt.ended_at = ended_at
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def sum_in_flight_reservations(db: AsyncSession, *, workflow_run_id: UUID) -> Decimal:
    """What the run's attempts still in flight hold of its budget.

    Derived, never stored as a counter: an attempt that settles, parks or is resolved
    as uncertain is no longer `in_flight`, so its hold ends without a write.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(NodeAttempt.reserved_usd), 0))
        .select_from(NodeAttempt)
        .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
        .where(
            NodeRun.workflow_run_id == workflow_run_id,
            NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value,
        )
    )
    return Decimal(total or 0)


async def sum_live_child_reservations(db: AsyncSession, *, workflow_run_id: UUID) -> Decimal:
    """What the runs this run's steps called still have to spend, while they live.

    Each live called run holds the part of its own cap it has not spent. What it has
    spent is already in this run's `child_cost`, so only the unspent part is counted.
    """
    terminal = [status.value for status in WorkflowRunStatus if status.is_terminal]
    unspent = func.greatest(
        0,
        WorkflowRun.budget_limit
        - WorkflowRun.spent_cost
        - func.coalesce(WorkflowRun.child_cost, 0),
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(unspent), 0))
        .select_from(WorkflowRun)
        .join(NodeRun, NodeRun.id == WorkflowRun.parent_node_run_id)
        .where(
            NodeRun.workflow_run_id == workflow_run_id,
            WorkflowRun.budget_limit.is_not(None),
            WorkflowRun.status.not_in(terminal),
        )
    )
    return Decimal(total or 0)


async def store_late_result(
    db: AsyncSession, *, attempt: NodeAttempt, late_result: dict[str, JsonValue]
) -> NodeAttempt:
    """Keep the result an attempt reported after it was resolved `uncertain`.

    The attempt's verdict, result and cost are untouched; this is the one other write
    a terminal attempt takes, and it is written once.
    """
    attempt.late_result = late_result
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def count_failed_attempts(db: AsyncSession, *, node_run_id: UUID) -> int:
    """How many of a node run's attempts failed or were interrupted.

    What the retry ceiling counts: an attempt that parked on a wait is not a
    failure, and must not use up the retries a later failure is owed.
    """
    return (
        await db.scalar(
            select(func.count())
            .select_from(NodeAttempt)
            .where(
                NodeAttempt.node_run_id == node_run_id,
                NodeAttempt.status.in_(
                    [NodeAttemptStatus.FAILED.value, NodeAttemptStatus.UNCERTAIN.value]
                ),
            )
        )
        or 0
    )


async def book_attempt_cost(
    db: AsyncSession, *, attempt: NodeAttempt, cost: Decimal, cost_is_partial: bool
) -> NodeAttempt:
    """Set an attempt's cost without touching its status or result.

    The one write a terminal attempt takes: its cost column is the ledger of
    what the call ran up, and a result that arrived too late to be accepted
    still ran it up.
    """
    attempt.cost = cost
    attempt.cost_is_partial = cost_is_partial
    db.add(attempt)
    await db.flush()
    await db.refresh(attempt)
    return attempt


async def list_orphaned_in_flight(
    db: AsyncSession, *, before: datetime, closed_before: datetime, limit: int = 100
) -> list[NodeAttempt]:
    """`in_flight` attempts nobody is still working on.

    The reconciler's starting point: an attempt committed `in_flight` before
    its handler ran (see `app.services.workflow_execution.dispatcher`), whose
    process died before settling it. Two shapes:

    - its claim is still `claimed` but the lease ran out before `before` -
      the worker died holding it;
    - its outbox row was closed under it (a cancel, a reclaim that failed the
      run for its deadline or budget) at least a lease ago, by
      `closed_before` - the grace lets a worker still running the handler
      settle it first, and without this shape such an attempt stayed
      `in_flight` for ever.

    An attempt with a live claim, or a pending row queued for it, is not
    orphaned. Ordered by the owning run's id: the sweep locks each run in turn
    and holds every lock until it commits, so any two sweeps must take them in
    the same order or they can deadlock each other.
    """
    same_node = DispatchOutbox.node_run_id == NodeAttempt.node_run_id
    still_held = (
        select(DispatchOutbox.id)
        .where(
            same_node,
            (DispatchOutbox.status == DispatchOutboxStatus.PENDING.value)
            | (
                (DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value)
                & (DispatchOutbox.lease_expires_at >= before)
            ),
        )
        .exists()
    )
    closed_recently = (
        select(DispatchOutbox.id)
        .where(
            same_node,
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.DONE.value, DispatchOutboxStatus.CANCELLED.value]
            ),
            DispatchOutbox.updated_at >= closed_before,
        )
        .exists()
    )
    result = await db.execute(
        select(NodeAttempt)
        .join(NodeRun, NodeRun.id == NodeAttempt.node_run_id)
        .where(
            NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value,
            ~still_held,
            ~closed_recently,
        )
        .order_by(NodeRun.workflow_run_id, NodeAttempt.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def bring_forward_outbox(db: AsyncSession, *, node_run_id: UUID) -> None:
    """Make a node run's pending dispatch row due now, by the database's clock.

    For a step parked on a timer that something else wakes early - a Wait step
    waiting for a call, once the call comes. A row already claimed or done is
    left alone: that dispatch is under way.
    """
    await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id == node_run_id,
            DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
        )
        .values(available_at=func.now(), submitted_at=func.now())
    )


async def create_outbox(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    node_run_id: UUID,
    available_at: datetime | None = None,
) -> DispatchOutbox:
    """Insert a dispatch row. Raises `IntegrityError` if one is already live.

    Callers that must treat a live row as "already dispatched" rather than a
    failure wrap this in `db.begin_nested()`, the same savepoint shape
    `UserService.confirm_email_change` uses for its own race.

    `available_at=None` means due now by the database's own clock - the clock
    `claim_outbox` compares against - so an application host running slightly
    ahead of the database cannot write a row that is not yet claimable when
    its job arrives.

    `submitted_at` is when the row's job is due to run - now, or `available_at`
    when later - for the caller (`dispatch_queue.queue_dispatch`) queues that job
    in the same transaction. The poll then looks only at rows still pending a
    lease after they came due.
    """
    outbox = DispatchOutbox(
        organization_id=organization_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        available_at=func.now() if available_at is None else available_at,
        submitted_at=func.now()
        if available_at is None
        else func.greatest(func.now(), available_at),
    )
    db.add(outbox)
    await db.flush()
    await db.refresh(outbox)
    return outbox


async def claim_outbox(
    db: AsyncSession, *, node_run_id: UUID, token: UUID, lease_expires_at: datetime
) -> DispatchOutbox | None:
    """The compare-and-swap claim: a `pending` row, or a `claimed` one whose lease expired.

    Matched on `node_run_id` rather than the outbox row's own id - the
    `workflow-dispatch-node` job carries `(workflow_run_id, node_run_id)`, and
    the partial unique index guarantees at most one live row per `node_run_id`
    to match.

    `status = 'claimed' AND lease_expires_at < now()` must be its own branch:
    `status = 'pending'` alone can never match a row this same claim already
    transitioned to `claimed`, which would permanently strand a run the
    instant its worker died mid-lease. `available_at <= now()` keeps a
    scheduled-but-not-yet-due retry from being claimed early by a direct wake
    racing the poller.
    """
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id == node_run_id,
            DispatchOutbox.available_at <= func.now(),
            (DispatchOutbox.status == DispatchOutboxStatus.PENDING.value)
            | (
                (DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value)
                & (DispatchOutbox.lease_expires_at < func.now())
            ),
        )
        .values(
            claimed_by=token,
            lease_expires_at=lease_expires_at,
            status=DispatchOutboxStatus.CLAIMED.value,
        )
        .returning(DispatchOutbox)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def take_due_for_submission(
    db: AsyncSession, *, resubmit_before: datetime, limit: int = 100
) -> list[DispatchOutbox]:
    """Deployment-wide: `pending` rows due now, stamped as submitted in the same statement.

    `workflow-dispatch-poll`'s scan. A row submitted at or after
    `resubmit_before` is left alone - its job is queued and will claim it - so
    a backed-up worker pool gets one job per row per interval, not one per tick.
    A row of an organization whose node kind is paused is left alone too: no job
    could claim it, and the oldest hundred of them would take every batch from
    the rows that need one. `SKIP LOCKED` leaves a row a worker is claiming right
    now to that worker.

    Unscoped like `agent_run_repo.list_stale_approvals` - the poller has no
    tenant of its own - and every write it triggers is still scoped by the
    node it dispatches. Lease-expired `claimed` rows are deliberately not
    here: reclaiming one safely needs to know whether an attempt was ever
    created for it, which is `workflow-reconcile`'s job, not the fast poller's.
    """
    due = (
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.status == DispatchOutboxStatus.PENDING.value,
            DispatchOutbox.available_at <= func.now(),
            or_(
                DispatchOutbox.submitted_at.is_(None),
                DispatchOutbox.submitted_at < resubmit_before,
            ),
            ~exists().where(
                BackgroundTaskKind.kind == WORKFLOW_DISPATCH_NODE.kind,
                BackgroundTaskKind.paused_at.is_not(None),
                or_(
                    BackgroundTaskKind.organization_id.is_(None),
                    BackgroundTaskKind.organization_id == DispatchOutbox.organization_id,
                ),
            ),
        )
        .order_by(DispatchOutbox.available_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return await _stamp_submitted(db, due)


async def take_stale_claims_for_resubmission(
    db: AsyncSession, *, before: datetime, resubmit_before: datetime, limit: int = 100
) -> list[DispatchOutbox]:
    """`claimed` rows past their lease with no `in_flight` attempt, stamped as submitted.

    The crash window between phase 1 (claim commits) and phase 2 (the
    `in_flight` attempt commits) - nothing was ever recorded for the
    reconciler's other query (`list_orphaned_in_flight`) to find, so this is
    the complementary scan: safe to reclaim exactly like a fresh `pending`
    row, since no call was ever made. The same once-per-interval rule as
    `take_due_for_submission` applies.
    """
    in_flight_node_runs = (
        select(NodeAttempt.node_run_id)
        .where(NodeAttempt.status == NodeAttemptStatus.IN_FLIGHT.value)
        .distinct()
    )
    stale = (
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
            DispatchOutbox.lease_expires_at.is_not(None),
            DispatchOutbox.lease_expires_at < before,
            DispatchOutbox.node_run_id.not_in(in_flight_node_runs),
            or_(
                DispatchOutbox.submitted_at.is_(None),
                DispatchOutbox.submitted_at < resubmit_before,
            ),
        )
        .order_by(DispatchOutbox.lease_expires_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return await _stamp_submitted(db, stale)


async def _stamp_submitted(db: AsyncSession, ids: Select[UUID]) -> list[DispatchOutbox]:
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(DispatchOutbox.id.in_(ids))
        .values(submitted_at=func.now())
        .returning(DispatchOutbox)
        # A row this session already holds would otherwise come back with its
        # pre-update values.
        .execution_options(synchronize_session=False, populate_existing=True)
    )
    return list(result.scalars().all())


async def renew_lease(
    db: AsyncSession, *, node_run_id: UUID, token: UUID, lease_seconds: float
) -> bool:
    """Extend a claim's lease, but only while it is still this token's open claim.

    The new expiry is `lease_seconds` from when the row is actually updated
    (`clock_timestamp()`, evaluated once the row lock is held), not from when
    the renewal was sent: a renewal that waits behind `begin_attempt`'s or
    `settle`'s lock on the row would otherwise land an expiry already spent.

    Returns whether it was: `False` means the row was reclaimed, closed or
    cancelled since, and the holder has lost it.
    """
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id == node_run_id,
            DispatchOutbox.claimed_by == token,
            DispatchOutbox.status == DispatchOutboxStatus.CLAIMED.value,
        )
        .values(
            lease_expires_at=func.clock_timestamp()
            + literal(timedelta(seconds=lease_seconds), Interval())
        )
        .returning(DispatchOutbox.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def mark_outbox_done(db: AsyncSession, *, outbox: DispatchOutbox) -> DispatchOutbox:
    outbox.status = DispatchOutboxStatus.DONE.value
    db.add(outbox)
    await db.flush()
    await db.refresh(outbox)
    return outbox


async def get_outbox_for_node_run_for_update(
    db: AsyncSession, *, node_run_id: UUID
) -> DispatchOutbox | None:
    """The row a claim on this node run is about, held for the caller's transaction.

    That is the live (`pending`/`claimed`) row when there is one - the partial
    unique index allows at most one - and otherwise the newest closed row.
    "Newest by `created_at`" alone is not enough: `created_at` is the inserting
    transaction's start time, so a row a long sweep inserted can carry an
    earlier stamp than a row another transaction inserted and closed meanwhile,
    and the live row would be the one never locked.

    `begin_attempt`, `settle` and the reconciler all take this lock, after the
    run's and the node run's, so a fencing check made under it stays true for
    the rest of the caller's transaction: `claim_outbox`'s reclaiming `UPDATE`
    needs the same row and waits for that transaction to end.
    """
    live_first = case(
        (
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
            0,
        ),
        else_=1,
    )
    result = await db.execute(
        select(DispatchOutbox)
        .where(DispatchOutbox.node_run_id == node_run_id)
        .order_by(live_first, DispatchOutbox.created_at.desc(), DispatchOutbox.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def has_live_outbox(db: AsyncSession, *, workflow_run_id: UUID) -> bool:
    """Whether any `pending`/`claimed` dispatch row remains for this run.

    What `WorkflowRunStatus.SUCCEEDED`'s "no rows" actually means - not that
    none exist at all (`done`/`cancelled` rows are kept, not deleted, for
    audit and reconciliation), only that nothing is left to dispatch.
    """
    result = await db.execute(
        select(DispatchOutbox.id)
        .where(
            DispatchOutbox.workflow_run_id == workflow_run_id,
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
        )
        .limit(1)
    )
    return result.first() is not None


async def cancel_live_outbox_for_run(db: AsyncSession, *, workflow_run_id: UUID) -> Sequence[UUID]:
    """Cancel every `pending` or `claimed` outbox row for a run. Returns the ids touched."""
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.workflow_run_id == workflow_run_id,
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
        )
        .values(status=DispatchOutboxStatus.CANCELLED.value)
        .returning(DispatchOutbox.id)
    )
    return result.scalars().all()


async def cancel_live_outbox_for_node_runs(
    db: AsyncSession, *, node_run_ids: Sequence[UUID]
) -> Sequence[UUID]:
    """Cancel every `pending` or `claimed` outbox row of these node runs. Returns the ids touched."""
    result = await db.execute(
        sql_update(DispatchOutbox)
        .where(
            DispatchOutbox.node_run_id.in_(node_run_ids),
            DispatchOutbox.status.in_(
                [DispatchOutboxStatus.PENDING.value, DispatchOutboxStatus.CLAIMED.value]
            ),
        )
        .values(status=DispatchOutboxStatus.CANCELLED.value)
        .returning(DispatchOutbox.id)
    )
    return result.scalars().all()


async def first_event_since(
    db: AsyncSession, *, node_run_id: UUID, kind: str, after_kind: str
) -> datetime | None:
    """When the step's current run of `kind` events began: the earliest one written after
    the step's latest `after_kind` event. `None` when there is none."""
    latest_after = (
        select(func.coalesce(func.max(WorkflowEvent.seq), 0))
        .where(WorkflowEvent.node_run_id == node_run_id, WorkflowEvent.kind == after_kind)
        .scalar_subquery()
    )
    return await db.scalar(
        select(func.min(WorkflowEvent.created_at)).where(
            WorkflowEvent.node_run_id == node_run_id,
            WorkflowEvent.kind == kind,
            WorkflowEvent.seq > latest_after,
        )
    )


async def append_event(
    db: AsyncSession,
    *,
    run: WorkflowRun,
    kind: str,
    node_run_id: UUID | None,
    payload: dict[str, Any],
) -> WorkflowEvent:
    """Append one event, consuming the run's own `next_event_seq`.

    The caller must already hold `run` from this transaction (typically row-
    locked via `get_run_for_update`) - the seq bump and the insert share this
    one flush, which is what keeps the counter and the row it numbers from
    disagreeing.

    `run` is refreshed as well as the event: the flush fires
    `TimestampMixin.updated_at`'s `onupdate`, which expires that attribute, and
    a caller reading it afterwards (the facade's own response) would otherwise
    lazy-load on an async session and raise `MissingGreenlet`.
    """
    seq = run.next_event_seq
    run.next_event_seq = seq + 1
    event = WorkflowEvent(
        organization_id=run.organization_id,
        workflow_run_id=run.id,
        seq=seq,
        kind=kind,
        node_run_id=node_run_id,
        payload=payload,
    )
    db.add(event)
    db.add(run)
    await db.flush()
    await db.refresh(event)
    await db.refresh(run)
    return event


async def list_events_since(
    db: AsyncSession,
    *,
    workflow_run_id: UUID,
    organization_id: UUID,
    after_seq: int | None,
    limit: int = 100,
) -> list[WorkflowEvent]:
    where = [
        WorkflowEvent.workflow_run_id == workflow_run_id,
        WorkflowEvent.organization_id == organization_id,
    ]
    if after_seq is not None:
        where.append(WorkflowEvent.seq > after_seq)
    result = await db.execute(
        select(WorkflowEvent).where(*where).order_by(WorkflowEvent.seq).limit(limit)
    )
    return list(result.scalars().all())


async def create_resource_ref(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_run_id: UUID,
    kind: str,
    ref: dict[str, Any],
) -> ResourceRef:
    resource_ref = ResourceRef(
        organization_id=organization_id, workflow_run_id=workflow_run_id, kind=kind, ref=ref
    )
    db.add(resource_ref)
    await db.flush()
    await db.refresh(resource_ref)
    return resource_ref


async def take_expired_runs(
    db: AsyncSession, *, now: datetime, limit: int
) -> list[tuple[UUID, list[str]]]:
    """Remove up to `limit` ended runs their workflow's settings no longer keep, and
    answer each one's id with the storage paths of the files it made.

    A run past `run_retention_days` since it ended, or one that succeeded more
    than a day ago in a workflow that does not keep succeeded runs. A run another
    run's chain starts from is left until that chain has gone, because the chain
    names it as its root. A called run also stays until its caller ends, because
    its waiting node needs that result to avoid calling it again. Sources of active retries
    and files imported by other retained runs stay too. The files' rows go with the run; the stored bytes are
    the caller's to unlink once this commits.
    """
    days = Workflow.settings["run_retention_days"].as_integer()
    keeps_succeeded = Workflow.settings["keep_succeeded_runs"].as_boolean()
    descendant = aliased(WorkflowRun)
    caller = aliased(WorkflowRun)
    retry = aliased(WorkflowRun)
    expired = (
        select(WorkflowRun.id)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            WorkflowRun.ended_at.is_not(None),
            or_(
                and_(
                    days.is_not(None),
                    WorkflowRun.ended_at < literal(now) - func.make_interval(0, 0, 0, days),
                ),
                and_(
                    keeps_succeeded.is_(False),
                    WorkflowRun.status == WorkflowRunStatus.SUCCEEDED.value,
                    WorkflowRun.ended_at < now - timedelta(days=1),
                ),
            ),
            ~exists().where(
                descendant.root_run_id == WorkflowRun.id, descendant.id != WorkflowRun.id
            ),
            ~exists(
                select(NodeRun.id)
                .join(caller, caller.id == NodeRun.workflow_run_id)
                .where(NodeRun.id == WorkflowRun.parent_node_run_id, caller.ended_at.is_(None))
            ),
            ~exists().where(
                retry.retry_of_run_id == WorkflowRun.id,
                retry.ended_at.is_(None),
            ),
            ~exists(
                select(ResourceRef.id)
                .join(
                    WorkflowFile, ResourceRef.ref["file_id"].astext == cast(WorkflowFile.id, String)
                )
                .where(
                    ResourceRef.kind == "file",
                    WorkflowFile.workflow_run_id == WorkflowRun.id,
                    ResourceRef.workflow_run_id != WorkflowRun.id,
                )
            ),
        )
        .order_by(WorkflowRun.ended_at)
        .limit(limit)
    )
    candidates = list((await db.execute(expired)).scalars().all())
    if not candidates:
        return []
    organizations = (
        await db.scalars(
            select(WorkflowRun.organization_id).where(WorkflowRun.id.in_(candidates)).distinct()
        )
    ).all()
    for organization_id in sorted(organizations):
        await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, organization_id)
    # Admission may have committed a reference while the lifecycle lock was busy.
    run_ids = list(
        (
            await db.scalars(
                expired.where(WorkflowRun.id.in_(candidates)).with_for_update(
                    of=WorkflowRun, skip_locked=True
                )
            )
        ).all()
    )
    if not run_ids:
        return []
    files = await db.execute(
        select(WorkflowFile.workflow_run_id, WorkflowFile.storage_path).where(
            WorkflowFile.workflow_run_id.in_(run_ids)
        )
    )
    paths: dict[UUID, list[str]] = {run_id: [] for run_id in run_ids}
    for run_id, storage_path in files.all():
        paths[run_id].append(storage_path)
    with_files = [identifier for identifier, stored in paths.items() if stored]
    if with_files:
        metadata = await db.execute(
            select(WorkflowRun.id, WorkflowRun.organization_id, WorkflowRun.workflow_id).where(
                WorkflowRun.id.in_(with_files)
            )
        )
        for identifier, organization_id, workflow_id in metadata.all():
            if await workflow_file_repo.files_are_referenced(
                db,
                organization_id=organization_id,
                workflow_id=workflow_id,
                run_id=identifier,
                include_same_workflow=True,
            ):
                run_ids.remove(identifier)
                paths.pop(identifier)
    if not run_ids:
        return []
    removed = (
        sql_delete(WorkflowRun)
        .where(WorkflowRun.id.in_(run_ids))
        .returning(
            WorkflowRun.id,
            WorkflowRun.organization_id,
            WorkflowRun.workflow_id,
            WorkflowRun.created_at,
            (WorkflowRun.spent_cost + WorkflowRun.child_cost).label("cost_usd"),
        )
        .cte("removed_runs")
    )
    # Only rows actually deleted are archived, even when sweepers overlap. This
    # statement and the deletion commit together; no content survives retention.
    await db.execute(
        insert(WorkflowRetainedSpend).from_select(
            ["run_id", "organization_id", "workflow_id", "admitted_at", "cost_usd"],
            select(
                removed.c.id,
                removed.c.organization_id,
                removed.c.workflow_id,
                removed.c.created_at,
                removed.c.cost_usd,
            ).where(removed.c.cost_usd > 0),
        )
    )
    await db.flush()
    return list(paths.items())


async def last_run_of_each(
    db: AsyncSession, *, organization_id: UUID, workflow_ids: Sequence[UUID]
) -> dict[UUID, WorkflowRun]:
    """Each workflow's most recent run, by workflow; one with none is absent.

    One query for a page of workflows: `DISTINCT ON` keeps the newest row of
    each, the id breaking a tie between runs created in the same instant.
    """
    if not workflow_ids:
        return {}
    result = await db.execute(
        select(WorkflowRun)
        .where(
            WorkflowRun.organization_id == organization_id,
            WorkflowRun.workflow_id.in_(workflow_ids),
        )
        .order_by(WorkflowRun.workflow_id, WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        .distinct(WorkflowRun.workflow_id)
    )
    return {run.workflow_id: run for run in result.scalars().all()}


async def get_run_called_by(db: AsyncSession, *, node_run_id: UUID) -> WorkflowRun | None:
    """The run a `workflow.run` step started, if it has started one."""
    result = await db.execute(
        select(WorkflowRun).where(WorkflowRun.parent_node_run_id == node_run_id).limit(1)
    )
    return result.scalar_one_or_none()


async def record_node_spend(
    db: AsyncSession,
    *,
    organization_id: UUID,
    attempt_id: UUID,
    cost_usd: Decimal,
    cost_is_partial: bool,
) -> None:
    """Keep the greatest known cumulative direct fee; settlements may repeat."""
    statement = insert(WorkflowNodeSpend).values(
        organization_id=organization_id,
        attempt_id=attempt_id,
        cost_usd=cost_usd,
        cost_is_partial=cost_is_partial,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[WorkflowNodeSpend.attempt_id],
            set_={
                "cost_usd": func.greatest(WorkflowNodeSpend.cost_usd, statement.excluded.cost_usd),
                "cost_is_partial": WorkflowNodeSpend.cost_is_partial
                | statement.excluded.cost_is_partial,
            },
            where=WorkflowNodeSpend.organization_id == organization_id,
        )
    )
    await db.flush()


async def node_spend_since(
    db: AsyncSession, *, organization_id: UUID, since: datetime, until: datetime | None = None
) -> Decimal:
    """Direct workflow provider fees, excluding fees already on agent_runs."""
    query = select(func.coalesce(func.sum(WorkflowNodeSpend.cost_usd), 0)).where(
        WorkflowNodeSpend.organization_id == organization_id, WorkflowNodeSpend.created_at >= since
    )
    if until is not None:
        query = query.where(WorkflowNodeSpend.created_at < until)
    return Decimal(await db.scalar(query) or 0)
