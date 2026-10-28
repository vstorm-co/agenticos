"""A workflow's own log: the lines its steps' Quick Logs wrote."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_log_entry import WorkflowLogEntry
from app.repositories._search import contains_ci


@dataclass(frozen=True, slots=True)
class LogFilters:
    """What a log listing is narrowed to; test runs only when asked for.

    `run` is a whole run id or the start of one (hex digits and dashes).
    """

    node_instance_id: UUID | None = None
    outcome: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    query: str | None = None
    include_test: bool = False
    run: str | None = None


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
        # Not the transaction's `now()`: lines written together keep the order they were written in.
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


_UUID_SHAPE = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
_HEX = frozenset("0123456789abcdefABCDEF")


def is_run_filter(run: str) -> bool:
    """A whole run id (dashes or not) or its first 4 or more characters, dashes where
    an id has them: the text cast a prefix is compared with."""
    if len(run) == 32:
        return all(char in _HEX for char in run)
    if not 4 <= len(run) <= len(_UUID_SHAPE):
        return False
    return all(
        char == "-" if shape == "-" else char in _HEX
        for char, shape in zip(run, _UUID_SHAPE, strict=False)
    )


def _run_matches(run: str) -> ColumnElement[bool]:
    """A whole id compares as a uuid, the start of one as text."""
    try:
        return WorkflowLogEntry.run_id == UUID(run)
    except ValueError:
        return cast(WorkflowLogEntry.run_id, String).startswith(run.lower(), autoescape=True)


async def list_for_workflow(
    db: AsyncSession,
    *,
    organization_id: UUID,
    workflow_id: UUID,
    filters: LogFilters,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[WorkflowLogEntry], int]:
    """One workflow's entries, newest first, narrowed by `filters`."""
    where = [
        WorkflowLogEntry.organization_id == organization_id,
        WorkflowLogEntry.workflow_id == workflow_id,
    ]
    if not filters.include_test:
        where.append(WorkflowLogEntry.is_test.is_(False))
    if filters.node_instance_id is not None:
        where.append(WorkflowLogEntry.node_instance_id == filters.node_instance_id)
    if filters.outcome is not None:
        where.append(WorkflowLogEntry.outcome == filters.outcome)
    if filters.created_from is not None:
        where.append(WorkflowLogEntry.created_at >= filters.created_from)
    if filters.created_to is not None:
        where.append(WorkflowLogEntry.created_at < filters.created_to)
    if filters.run is not None:
        where.append(_run_matches(filters.run))
    if filters.query:
        where.append(contains_ci(WorkflowLogEntry.message, filters.query))
    total = await db.scalar(select(func.count()).select_from(WorkflowLogEntry).where(*where)) or 0
    result = await db.execute(
        select(WorkflowLogEntry)
        .where(*where)
        .order_by(WorkflowLogEntry.created_at.desc(), WorkflowLogEntry.id)
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
        .order_by(WorkflowLogEntry.created_at, WorkflowLogEntry.id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total
