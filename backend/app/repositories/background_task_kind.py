"""Data access for the circuit breaker on each kind of background job (#2219)."""

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_task_kind import BackgroundTaskKind


async def record_death(db: AsyncSession, kind: str) -> int:
    """Count one more worker death for `kind`. Answers the run of deaths it is now on."""
    statement = insert(BackgroundTaskKind).values(kind=kind, consecutive_deaths=1)
    result = await db.execute(
        statement.on_conflict_do_update(
            index_elements=[BackgroundTaskKind.kind],
            set_={"consecutive_deaths": BackgroundTaskKind.consecutive_deaths + 1},
        ).returning(BackgroundTaskKind.consecutive_deaths)
    )
    return result.scalar_one()


async def record_survival(db: AsyncSession, kind: str) -> None:
    """End `kind`'s run of deaths: a job of it finished without killing anything.

    A no-op for a kind that has no run going, which is nearly every call - so
    no row is created for a kind that never died.
    """
    await db.execute(
        update(BackgroundTaskKind)
        .where(BackgroundTaskKind.kind == kind, BackgroundTaskKind.consecutive_deaths > 0)
        .values(consecutive_deaths=0)
    )


async def record_lease_lost(db: AsyncSession, kind: str) -> None:
    """Count a job of `kind` that finished after another worker had taken it over."""
    statement = insert(BackgroundTaskKind).values(kind=kind, lease_lost=1)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[BackgroundTaskKind.kind],
            set_={"lease_lost": BackgroundTaskKind.lease_lost + 1},
        )
    )


async def pause(db: AsyncSession, kind: str, *, reason: str) -> bool:
    """Stop workers claiming `kind`. `False` when it was paused already."""
    statement = insert(BackgroundTaskKind).values(
        kind=kind, paused_at=func.now(), paused_reason=reason
    )
    result = await db.execute(
        statement.on_conflict_do_update(
            index_elements=[BackgroundTaskKind.kind],
            set_={"paused_at": func.now(), "paused_reason": reason},
            where=BackgroundTaskKind.paused_at.is_(None),
        ).returning(BackgroundTaskKind.kind)
    )
    return result.scalar_one_or_none() is not None


async def resume(db: AsyncSession, kind: str) -> bool:
    """Let workers claim `kind` again, starting its count of deaths afresh. `False` when not paused."""
    result = await db.execute(
        update(BackgroundTaskKind)
        .where(BackgroundTaskKind.kind == kind, BackgroundTaskKind.paused_at.is_not(None))
        .values(paused_at=None, paused_reason=None, consecutive_deaths=0)
        .returning(BackgroundTaskKind.kind)
    )
    return result.scalar_one_or_none() is not None


async def list_all(db: AsyncSession) -> Sequence[BackgroundTaskKind]:
    result = await db.execute(select(BackgroundTaskKind).order_by(BackgroundTaskKind.kind))
    return result.scalars().all()
