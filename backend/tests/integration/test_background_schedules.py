"""The scheduler's decisions, asked of the database the schedules live in (#2219).

Time is passed in rather than read from the clock, so "two hours later" is
an argument, not a wait: each test sets `next_run_at` where the case needs it
and fires at a chosen instant.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.background_job import BackgroundJob
from app.db.models.background_schedule import BackgroundSchedule
from app.repositories import background_job as job_repo
from app.worker import jobs
from app.worker.jobs import Tick
from app.worker.schedules import SCHEDULES, Misfire, Overlap, Schedule, declare, fire_due

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
HOURLY = Schedule("hourly", jobs.REAP_STALE_RUNS, timedelta(hours=1))

Sessions = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@pytest.fixture
def sessions(engine: AsyncEngine) -> Sessions:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with maker() as db, db.begin():
            yield db

    return session


async def _declare(sessions: Sessions, *schedules: Schedule, now: datetime = NOW) -> None:
    async with sessions() as db:
        await declare(db, schedules, now=now)


async def _due_at(sessions: Sessions, name: str, at: datetime) -> None:
    async with sessions() as db:
        await db.execute(
            update(BackgroundSchedule).where(BackgroundSchedule.name == name).values(next_run_at=at)
        )


async def _fire(sessions: Sessions, *schedules: Schedule, now: datetime) -> list[str]:
    async with sessions() as db:
        return await fire_due(db, schedules, now=now)


async def _row(sessions: Sessions, name: str) -> BackgroundSchedule:
    async with sessions() as db:
        row = await db.get(BackgroundSchedule, name)
    assert row is not None
    return row


async def _jobs(sessions: Sessions) -> list[BackgroundJob]:
    async with sessions() as db:
        return list(
            (await db.execute(select(BackgroundJob).order_by(BackgroundJob.created_at))).scalars()
        )


async def test_an_occurrence_on_time_fires_once_and_moves_on_one_interval(
    sessions: Sessions,
) -> None:
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW)

    assert await _fire(sessions, HOURLY, now=NOW + timedelta(seconds=5)) == ["hourly"]
    assert await _fire(sessions, HOURLY, now=NOW + timedelta(seconds=6)) == []

    [job] = await _jobs(sessions)
    assert (job.kind, job.schedule_name) == ("reap-stale-runs", "hourly")
    assert jobs.REAP_STALE_RUNS.load(job.payload) == Tick(scheduled_for=NOW)
    row = await _row(sessions, "hourly")
    assert row.next_run_at == NOW + timedelta(hours=1)
    assert row.last_job_id == job.id


async def test_an_occurrence_within_grace_fires_as_if_on_time(sessions: Sessions) -> None:
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW)

    await _fire(sessions, HOURLY, now=NOW + timedelta(seconds=59))

    [job] = await _jobs(sessions)
    assert jobs.REAP_STALE_RUNS.load(job.payload).scheduled_for == NOW


async def test_a_backlog_fires_once_for_the_latest_occurrence_and_keeps_the_grid(
    sessions: Sessions,
) -> None:
    """Down for five and a half hours: one job, for 17:00, and next at 18:00 - not five jobs."""
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW)

    await _fire(sessions, HOURLY, now=NOW + timedelta(hours=5, minutes=30))

    [job] = await _jobs(sessions)
    assert jobs.REAP_STALE_RUNS.load(job.payload).scheduled_for == NOW + timedelta(hours=5)
    assert (await _row(sessions, "hourly")).next_run_at == NOW + timedelta(hours=6)


async def test_a_skipping_schedule_late_past_grace_fires_nothing_and_waits(
    sessions: Sessions,
) -> None:
    skipping = Schedule("hourly", jobs.REAP_STALE_RUNS, timedelta(hours=1), misfire=Misfire.SKIP)
    await _declare(sessions, skipping)
    await _due_at(sessions, "hourly", NOW)

    assert await _fire(sessions, skipping, now=NOW + timedelta(minutes=2)) == []

    assert await _jobs(sessions) == []
    row = await _row(sessions, "hourly")
    assert row.next_run_at == NOW + timedelta(hours=1)
    assert row.last_fired_at is None


async def test_an_occurrence_while_the_last_job_still_runs_is_skipped(sessions: Sessions) -> None:
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW)
    await _fire(sessions, HOURLY, now=NOW)

    assert await _fire(sessions, HOURLY, now=NOW + timedelta(hours=1)) == []

    assert len(await _jobs(sessions)) == 1
    assert (await _row(sessions, "hourly")).next_run_at == NOW + timedelta(hours=2)


async def test_a_queueing_schedule_lets_one_wait_behind_the_running_job_and_no_more(
    sessions: Sessions,
) -> None:
    queueing = Schedule(
        "report", jobs.WEEKLY_USAGE_REPORT, timedelta(hours=1), overlap=Overlap.QUEUE
    )
    await _declare(sessions, queueing)
    await _due_at(sessions, "report", NOW)
    await _fire(sessions, queueing, now=NOW)
    async with sessions() as db:
        assert await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=5))

    assert await _fire(sessions, queueing, now=NOW + timedelta(hours=1)) == ["report"]
    assert await _fire(sessions, queueing, now=NOW + timedelta(hours=2)) == []

    assert [job.status for job in await _jobs(sessions)] == ["running", "queued"]


async def test_an_allowing_schedule_fires_alongside_the_running_job(sessions: Sessions) -> None:
    allowing = Schedule("hourly", jobs.REAP_STALE_RUNS, timedelta(hours=1), overlap=Overlap.ALLOW)
    await _declare(sessions, allowing)
    await _due_at(sessions, "hourly", NOW)
    await _fire(sessions, allowing, now=NOW)
    await _fire(sessions, allowing, now=NOW + timedelta(hours=1))

    assert len(await _jobs(sessions)) == 2


async def test_redeclaring_keeps_where_a_schedule_is_up_to(sessions: Sessions) -> None:
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW + timedelta(minutes=40))

    await _declare(sessions, HOURLY, now=NOW + timedelta(minutes=10))

    assert (await _row(sessions, "hourly")).next_run_at == NOW + timedelta(minutes=40)


async def test_a_shortened_interval_does_not_wait_out_the_old_gap(sessions: Sessions) -> None:
    daily = Schedule("sweep", jobs.REAP_STALE_RUNS, timedelta(days=1))
    await _declare(sessions, daily)
    await _due_at(sessions, "sweep", NOW + timedelta(hours=20))

    await _declare(sessions, Schedule("sweep", jobs.REAP_STALE_RUNS, timedelta(hours=1)))

    row = await _row(sessions, "sweep")
    assert (row.interval_seconds, row.next_run_at) == (3600, NOW + timedelta(hours=1))


async def test_a_schedule_the_code_no_longer_declares_is_forgotten(sessions: Sessions) -> None:
    await _declare(sessions, HOURLY, Schedule("retired", jobs.REAP_STALE_RUNS, timedelta(hours=1)))
    await _declare(sessions, HOURLY)

    async with sessions() as db:
        names = (await db.execute(select(BackgroundSchedule.name))).scalars().all()
    assert names == ["hourly"]


async def test_a_new_deployments_schedules_start_spread_within_a_minute(sessions: Sessions) -> None:
    await _declare(sessions, *SCHEDULES)

    async with sessions() as db:
        rows = (await db.execute(select(BackgroundSchedule))).scalars().all()
    starts = sorted(row.next_run_at for row in rows)
    assert len(rows) == len(SCHEDULES)
    assert starts[0] == NOW
    assert starts[-1] < NOW + timedelta(minutes=1)
    assert len(set(starts)) == len(starts)


async def test_two_workers_ticking_at_once_fire_a_schedule_once(sessions: Sessions) -> None:
    await _declare(sessions, HOURLY)
    await _due_at(sessions, "hourly", NOW)

    results = await asyncio.gather(*(_fire(sessions, HOURLY, now=NOW) for _ in range(5)))

    assert sorted(name for batch in results for name in batch) == ["hourly"]
    assert len(await _jobs(sessions)) == 1


async def test_every_declared_schedule_names_a_task_the_worker_knows() -> None:
    assert {schedule.task.kind for schedule in SCHEDULES} <= set(jobs.TASKS)
    assert len({schedule.name for schedule in SCHEDULES}) == len(SCHEDULES)
