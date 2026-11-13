"""A workflow's own log: the lines its steps' Quick Logs wrote."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, String, Text, cast, func, literal, select, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow import Workflow
from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.db.models.workflow_run import WorkflowRun
from app.repositories import workflow as workflow_repo
from app.repositories._search import contains_ci
from app.schemas.workflow_log_entry import LogFilters


@dataclass(frozen=True, slots=True)
class LogDayCount:
    """How many lines left by one outcome on one day."""

    day: date
    outcome: str
    lines: int


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    run_id: UUID,
    node_instance_id: UUID,
    step_label: str,
    outcome: str,
    status: str,
    message: str,
    is_test: bool,
    is_pinned: bool,
) -> WorkflowLogEntry:
    row = WorkflowLogEntry(
        organization_id=organization_id,
        workflow_id=workflow_id,
        run_id=run_id,
        node_instance_id=node_instance_id,
        step_label=step_label,
        outcome=outcome,
        status=status,
        message=message,
        is_test=is_test,
        is_pinned=is_pinned,
        # Not the transaction's `now()`, which is one instant for every line of a transaction.
        # What orders lines written together is `seq`; this is when each was written.
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


def _left_by() -> ColumnElement[Sequence[str]]:
    """The ports a line left by: a line that left by several lists them joined by a comma."""
    return type_coerce(func.string_to_array(WorkflowLogEntry.outcome, ", "), ARRAY(Text))


def _ports(outcomes: list[str]) -> list[str]:
    """The ports named, each value split the way a line stores several: joined by `", "`."""
    return [port for outcome in outcomes for port in outcome.split(", ")]


def _run_matches(run: str) -> ColumnElement[bool]:
    """A whole id compares as a uuid, the start of one as text."""
    try:
        return WorkflowLogEntry.run_id == UUID(run)
    except ValueError:
        return cast(WorkflowLogEntry.run_id, String).startswith(run.lower(), autoescape=True)


def _public_runs_only() -> ColumnElement[bool]:
    """Only lines of public-origin runs, the runs list's `public_only` rule for a key."""
    return (
        select(WorkflowRun.id)
        .where(WorkflowRun.id == WorkflowLogEntry.run_id, WorkflowRun.public_origin.is_(True))
        .exists()
    )


def _scope(
    organization_id: UUID, workflow_id: UUID, filters: LogFilters, *, public_only: bool = False
) -> list[ColumnElement[bool]]:
    """The conditions a listing and a summary of one workflow's log share."""
    where = [
        WorkflowLogEntry.organization_id == organization_id,
        WorkflowLogEntry.workflow_id == workflow_id,
    ]
    if public_only:
        where.append(_public_runs_only())
    if not filters.include_test:
        where.append(WorkflowLogEntry.is_test.is_(False))
    if filters.node_instance_id is not None:
        where.append(WorkflowLogEntry.node_instance_id == filters.node_instance_id)
    if filters.outcome is not None:
        where.append(_left_by().overlap(literal(_ports(filters.outcome), ARRAY(Text))))
    if filters.created_from is not None:
        where.append(WorkflowLogEntry.created_at >= filters.created_from)
    if filters.created_to is not None:
        where.append(WorkflowLogEntry.created_at < filters.created_to)
    if filters.run is not None:
        where.append(_run_matches(filters.run))
    if filters.query:
        where.append(contains_ci(WorkflowLogEntry.message, filters.query))
    return where


async def list_for_workflow(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    filters: LogFilters,
    public_only: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkflowLogEntry], int]:
    """One workflow's entries, newest first, narrowed by `filters`."""
    where = _scope(organization_id, workflow_id, filters, public_only=public_only)
    total = await db.scalar(select(func.count()).select_from(WorkflowLogEntry).where(*where)) or 0
    result = await db.execute(
        select(WorkflowLogEntry)
        .where(*where)
        .order_by(WorkflowLogEntry.created_at.desc(), WorkflowLogEntry.seq.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def list_for_run(
    db: AsyncSession, *, organization_id: UUID, run_id: UUID, skip: int = 0, limit: int = 200
) -> tuple[list[WorkflowLogEntry], int]:
    """A run's entries, in the order it wrote them."""
    where = [
        WorkflowLogEntry.organization_id == organization_id,
        WorkflowLogEntry.run_id == run_id,
    ]
    total = await db.scalar(select(func.count()).select_from(WorkflowLogEntry).where(*where)) or 0
    result = await db.execute(
        select(WorkflowLogEntry)
        .where(*where)
        .order_by(WorkflowLogEntry.seq)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def count_by_day(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    filters: LogFilters,
    since: datetime,
    until: datetime,
    tz: str,
    public_only: bool = False,
) -> list[LogDayCount]:
    """One workflow's entries written from `since` up to `until`, narrowed by `filters`,
    counted by the day in time zone `tz` and by outcome, in one grouped query."""
    day = func.date(func.timezone(tz, WorkflowLogEntry.created_at)).label("day")
    result = await db.execute(
        select(day, WorkflowLogEntry.outcome, func.count().label("lines"))
        .where(
            *_scope(organization_id, workflow_id, filters, public_only=public_only),
            WorkflowLogEntry.created_at >= since,
            WorkflowLogEntry.created_at < until,
        )
        .group_by(day, WorkflowLogEntry.outcome)
    )
    return [LogDayCount(day=row.day, outcome=row.outcome, lines=row.lines) for row in result.all()]


def _recent_scope(
    organization_id: UUID,
    visible_to_user_id: UUID | None,
    shared_workflow_ids: list[UUID] | None,
    public_only: bool,
) -> list[ColumnElement[bool]]:
    """Real runs' lines of the workflows a caller may see: with no `visible_to_user_id` their
    role reaches every workflow, otherwise the workflows `workflow_repo.visible_to` names."""
    where = [
        WorkflowLogEntry.organization_id == organization_id,
        WorkflowLogEntry.is_test.is_(False),
    ]
    if public_only:
        where.append(_public_runs_only())
    if visible_to_user_id is not None:
        visible = select(Workflow.id).where(
            Workflow.organization_id == organization_id,
            workflow_repo.visible_to(
                user_id=visible_to_user_id, shared_ids=shared_workflow_ids or []
            ),
        )
        where.append(WorkflowLogEntry.workflow_id.in_(visible))
    return where


async def list_recent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    visible_to_user_id: UUID | None,
    shared_workflow_ids: list[UUID] | None,
    public_only: bool = False,
    skip: int = 0,
    limit: int = 50,
) -> list[tuple[WorkflowLogEntry, str]]:
    """The newest real-run entries across the visible workflows, each with its workflow's name.

    No total: counting every entry of a busy organization is the cost a card of the newest
    few never needs."""
    where = _recent_scope(organization_id, visible_to_user_id, shared_workflow_ids, public_only)
    result = await db.execute(
        select(WorkflowLogEntry, Workflow.name)
        .join(Workflow, Workflow.id == WorkflowLogEntry.workflow_id)
        .where(*where)
        .order_by(WorkflowLogEntry.created_at.desc(), WorkflowLogEntry.seq.desc())
        .offset(skip)
        .limit(limit)
    )
    return [(entry, name) for entry, name in result.all()]


async def count_recent_by_outcome(
    db: AsyncSession,
    *,
    organization_id: UUID,
    visible_to_user_id: UUID | None,
    shared_workflow_ids: list[UUID] | None,
    since: datetime,
    public_only: bool = False,
) -> dict[str, int]:
    """Real-run entries of the visible workflows written since `since`, counted by outcome."""
    result = await db.execute(
        select(WorkflowLogEntry.outcome, func.count())
        .where(
            *_recent_scope(organization_id, visible_to_user_id, shared_workflow_ids, public_only),
            WorkflowLogEntry.created_at >= since,
        )
        .group_by(WorkflowLogEntry.outcome)
    )
    return dict(result.all())


async def count_matching(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    outcomes: list[str],
    node_instance_id: UUID | None,
    message_contains: str | None,
    since: datetime,
    until: datetime,
    after: datetime | None = None,
) -> int:
    """Real-run lines of one workflow written from `since` through `until` that left by any of
    `outcomes` (a line that left by several lists them joined by a comma), narrowed to one
    step and to messages containing text when given. `after`, when given, leaves out lines
    written at or before it: a line at the instant of an earlier alert was counted by it."""
    where = [
        WorkflowLogEntry.organization_id == organization_id,
        WorkflowLogEntry.workflow_id == workflow_id,
        WorkflowLogEntry.is_test.is_(False),
        WorkflowLogEntry.created_at >= since,
        WorkflowLogEntry.created_at <= until,
        _left_by().overlap(literal(outcomes, ARRAY(Text))),
    ]
    if after is not None:
        where.append(WorkflowLogEntry.created_at > after)
    if node_instance_id is not None:
        where.append(WorkflowLogEntry.node_instance_id == node_instance_id)
    if message_contains:
        where.append(contains_ci(WorkflowLogEntry.message, message_contains))
    return await db.scalar(select(func.count()).select_from(WorkflowLogEntry).where(*where)) or 0
