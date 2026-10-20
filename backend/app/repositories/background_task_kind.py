"""Data access for the circuit breaker on each kind of background job (#2219).

A breaker's scope is a kind in one organization, or the whole kind when
`organization_id` is `None` (#2248). The upserts arbitrate on the scope's unique
constraint, which treats two `NULL` organizations as the same scope.

A job keeps its organization's id after the organization is deleted - the purge
itself queues clean-up under it - so a scope can name an organization the foreign
key no longer admits. The upserts then write nothing rather than fail: a refused
insert would roll back the rescue it is part of and leave the job `running` on
every pass. The job's own attempts still bound it; only the breaker, which exists
to protect that organization's other work, has nothing left to protect.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_task_kind import BackgroundTaskKind
from app.db.models.organization import Organization

_SCOPE = "background_task_kinds_scope_key"


def _scoped_insert(
    kind: str, organization_id: UUID | None, **values: int | str | ColumnElement[datetime]
) -> Insert:
    """An insert of the scope's row that writes nothing for an organization since deleted."""
    columns = {"kind": kind, "organization_id": organization_id, **values}
    table = BackgroundTaskKind.__table__
    row = select(
        *(
            (
                value if isinstance(value, ColumnElement) else literal(value, table.c[name].type)
            ).label(name)
            for name, value in columns.items()
        )
    )
    if organization_id is not None:
        row = row.where(exists().where(Organization.id == organization_id))
    return insert(BackgroundTaskKind).from_select(list(columns), row)


def _in_scope(kind: str, organization_id: UUID | None) -> ColumnElement[bool]:
    return (
        BackgroundTaskKind.kind == kind
    ) & BackgroundTaskKind.organization_id.is_not_distinct_from(organization_id)


async def record_death(db: AsyncSession, kind: str, organization_id: UUID | None) -> int:
    """Count one more worker death in this scope. Answers the run of deaths it is now on.

    0 for an organization deleted since the job was queued: nothing was counted.
    """
    statement = _scoped_insert(kind, organization_id, consecutive_deaths=1)
    result = await db.execute(
        statement.on_conflict_do_update(
            constraint=_SCOPE,
            set_={"consecutive_deaths": BackgroundTaskKind.consecutive_deaths + 1},
        ).returning(BackgroundTaskKind.consecutive_deaths)
    )
    return result.scalar_one_or_none() or 0


async def record_survival(db: AsyncSession, kind: str, organization_id: UUID | None) -> None:
    """End this scope's run of deaths: a job of it finished without killing anything.

    A no-op for a scope that has no run going, which is nearly every call - so
    no row is created for one that never died.
    """
    await db.execute(
        update(BackgroundTaskKind)
        .where(_in_scope(kind, organization_id), BackgroundTaskKind.consecutive_deaths > 0)
        .values(consecutive_deaths=0)
    )


async def record_lease_lost(db: AsyncSession, kind: str, organization_id: UUID | None) -> None:
    """Count a job in this scope that finished after another worker had taken it over."""
    statement = _scoped_insert(kind, organization_id, lease_lost=1)
    await db.execute(
        statement.on_conflict_do_update(
            constraint=_SCOPE,
            set_={"lease_lost": BackgroundTaskKind.lease_lost + 1},
        )
    )


async def pause(db: AsyncSession, kind: str, organization_id: UUID | None, *, reason: str) -> bool:
    """Stop workers claiming `kind` in this scope. `False` when it was paused already.

    `False` too for an organization deleted since: there is nothing of it left to pause.
    """
    statement = _scoped_insert(kind, organization_id, paused_at=func.now(), paused_reason=reason)
    result = await db.execute(
        statement.on_conflict_do_update(
            constraint=_SCOPE,
            set_={"paused_at": func.now(), "paused_reason": reason},
            where=BackgroundTaskKind.paused_at.is_(None),
        ).returning(BackgroundTaskKind.id)
    )
    return result.scalar_one_or_none() is not None


async def resume(db: AsyncSession, kind: str, organization_id: UUID | None) -> bool:
    """Let workers claim `kind` in this scope again, its deaths counted afresh. `False` when not paused."""
    result = await db.execute(
        update(BackgroundTaskKind)
        .where(_in_scope(kind, organization_id), BackgroundTaskKind.paused_at.is_not(None))
        .values(paused_at=None, paused_reason=None, consecutive_deaths=0)
        .returning(BackgroundTaskKind.id)
    )
    return result.scalar_one_or_none() is not None


async def get(
    db: AsyncSession, kind: str, organization_id: UUID | None
) -> tuple[BackgroundTaskKind, str | None] | None:
    """One scope's row, and the name of its organization."""
    result = await db.execute(
        select(BackgroundTaskKind, Organization.name)
        .outerjoin(Organization, Organization.id == BackgroundTaskKind.organization_id)
        .where(_in_scope(kind, organization_id))
    )
    row = result.tuples().one_or_none()
    return None if row is None else (row[0], row[1])


async def list_all(db: AsyncSession) -> Sequence[tuple[BackgroundTaskKind, str | None]]:
    """Every scope's row, with its organization's name, by kind and then organization."""
    result = await db.execute(
        select(BackgroundTaskKind, Organization.name)
        .outerjoin(Organization, Organization.id == BackgroundTaskKind.organization_id)
        .order_by(BackgroundTaskKind.kind, Organization.name.nulls_first())
    )
    return result.tuples().all()
