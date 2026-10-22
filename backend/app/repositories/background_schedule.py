"""Data access for the deployment's own recurring jobs (#2219)."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_schedule import BackgroundSchedule


async def declare(
    db: AsyncSession,
    *,
    name: str,
    kind: str,
    interval_seconds: int,
    overlap: str,
    misfire: str,
    grace_seconds: int,
    now: datetime,
    first_run_at: datetime,
) -> None:
    """Write a schedule the code declares, keeping where an existing one is up to.

    A new schedule first fires at `first_run_at`. An existing one keeps its
    `next_run_at`, so a restart neither fires everything at once nor forgets
    the backlog - unless its interval was shortened below the wait still left,
    which would otherwise hold the new, tighter schedule to the old gap once.
    """
    statement = insert(BackgroundSchedule).values(
        name=name,
        kind=kind,
        interval_seconds=interval_seconds,
        overlap=overlap,
        misfire=misfire,
        grace_seconds=grace_seconds,
        next_run_at=first_run_at,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[BackgroundSchedule.name],
            set_={
                "kind": statement.excluded.kind,
                "interval_seconds": statement.excluded.interval_seconds,
                "overlap": statement.excluded.overlap,
                "misfire": statement.excluded.misfire,
                "grace_seconds": statement.excluded.grace_seconds,
            },
        )
    )
    await db.execute(
        update(BackgroundSchedule)
        .where(
            BackgroundSchedule.name == name,
            BackgroundSchedule.next_run_at > now + timedelta(seconds=interval_seconds),
        )
        .values(next_run_at=now + timedelta(seconds=interval_seconds))
    )


async def forget_undeclared(db: AsyncSession, *, declared: Sequence[str]) -> int:
    """Remove the schedules the code no longer declares. Answers how many went."""
    rows = await db.execute(
        delete(BackgroundSchedule)
        .where(BackgroundSchedule.name.not_in(declared))
        .returning(BackgroundSchedule.name)
    )
    return len(rows.all())


async def claim_due(db: AsyncSession, *, now: datetime, limit: int) -> Sequence[BackgroundSchedule]:
    """The schedules due at `now`, locked for this caller and skipped by every other.

    The lock is held until the caller commits, so the occurrence it fires and
    the `next_run_at` it moves on to land together: two workers ticking at the
    same instant fire a schedule once.
    """
    result = await db.execute(
        select(BackgroundSchedule)
        .where(BackgroundSchedule.next_run_at <= now)
        .order_by(BackgroundSchedule.next_run_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return result.scalars().all()


async def advance(
    db: AsyncSession,
    name: str,
    *,
    next_run_at: datetime,
    fired_at: datetime | None,
    job_id: UUID | None,
) -> None:
    """Move a claimed schedule on, recording the job it fired when it fired one."""
    values: dict[str, object] = {"next_run_at": next_run_at}
    if fired_at is not None:
        values["last_fired_at"] = fired_at
        values["last_job_id"] = job_id
    await db.execute(
        update(BackgroundSchedule).where(BackgroundSchedule.name == name).values(**values)
    )


async def list_all(db: AsyncSession) -> Sequence[BackgroundSchedule]:
    result = await db.execute(select(BackgroundSchedule).order_by(BackgroundSchedule.name))
    return result.scalars().all()
