"""The worker, end to end, on a real database and real child processes (#2219).

These are the failures the queue was built against, each reproduced rather
than mocked: a job that eats memory until its process is stopped, a process
the kernel kills, a worker that dies holding a job and is replaced by one
under another name, a database that goes away, a shutdown in the middle of a
job, and a kind of job that keeps killing its workers. Each asserts the job's
final state and what is written on it - never that a function was called.
"""

import asyncio
import contextlib
import dataclasses
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.background_job import BackgroundJob
from app.db.models.background_task_kind import BackgroundTaskKind
from app.db.models.background_worker import BackgroundWorker
from app.repositories import background_job as job_repo
from app.repositories import background_task_kind as kind_repo
from app.worker.executors import ChildPool, Executor, InProcessExecutor
from app.worker.jobs import Pool, Task
from app.worker.listener import asyncpg_dsn, listener
from app.worker.runtime import Worker, WorkerSettings
from tests import worker_handlers
from tests.worker_handlers import Note

pytestmark = pytest.mark.anyio

PATIENCE = 60.0

SYSTEM_TASKS = worker_handlers.tasks(Pool.SYSTEM)
INGEST_TASKS = worker_handlers.tasks(Pool.INGEST)


ENDED: list[tuple[str, str]] = []
"""Every job the worker said had ended for good, with why: `(kind, why)`."""


@pytest.fixture(autouse=True)
def _forget_endings() -> None:
    ENDED.clear()


@pytest.fixture
def sessions(
    engine: AsyncEngine,
) -> Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        async with maker() as db, db.begin():
            yield db

    return session


@pytest.fixture
def pauses() -> list[tuple[str, str]]:
    return []


def _settings(tmp_path: Path, **overrides: object) -> WorkerSettings:
    base = WorkerSettings(
        worker_id="test-worker",
        hostname="test-host",
        lease=timedelta(seconds=3),
        heartbeat_every=0.5,
        rescue_every=0.3,
        schedule_every=0.3,
        poll_every=0.2,
        drain_timeout=5.0,
        breaker_deaths=5,
        retry_base=timedelta(0),
        outage_cap=0.5,
        health_file=tmp_path / "alive",
    )
    return dataclasses.replace(base, **overrides)


@asynccontextmanager
async def running(
    sessions: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
    tmp_path: Path,
    pauses: list[tuple[str, str]],
    *,
    ingest: bool = False,
    listen_dsn: str | None = None,
    **overrides: object,
) -> AsyncGenerator[Worker]:
    """A worker serving the system pool in-process - and the ingest pool in children, if asked."""
    executors: dict[Pool, Executor] = {
        Pool.SYSTEM: InProcessExecutor(worker_handlers.bound(Pool.SYSTEM), concurrency=4)
    }
    tasks = {task.kind: task for task in SYSTEM_TASKS.values()}
    if ingest:
        executors[Pool.INGEST] = ChildPool(
            size=1,
            handlers="tests.worker_handlers:handlers",
            memory_limit_bytes=256 * 2**20,
            max_jobs=50,
            watch_every=0.1,
            respawn_backoff=0.1,
        )
        tasks.update({task.kind: task for task in INGEST_TASKS.values()})

    async def on_pause(
        _db: AsyncSession, kind: str, _organization_id: UUID | None, reason: str
    ) -> None:
        pauses.append((kind, reason))

    async def on_ended(kind: str, _payload: object, why: str) -> None:
        ENDED.append((kind, why))

    worker = Worker(
        settings=_settings(tmp_path, **overrides),
        executors=executors,
        tasks=tasks,
        sessions=sessions,
        on_pause=on_pause,
        on_ended=on_ended,
        listen=None if listen_dsn is None else listener(listen_dsn),
    )
    stop = asyncio.Event()
    serving = asyncio.create_task(worker.run(stop))
    try:
        yield worker
    finally:
        stop.set()
        await asyncio.wait_for(serving, timeout=PATIENCE)


async def _enqueue(
    sessions: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
    task: Task[Note],
    note: Note | None = None,
) -> UUID:
    async with sessions() as db:
        job_id = await job_repo.add(
            db,
            kind=task.kind,
            pool=task.pool.value,
            payload=task.dump(note or Note()),
            max_attempts=task.max_attempts,
            priority=int(task.priority),
        )
    assert job_id is not None
    return job_id


async def _job(
    sessions: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]], job_id: UUID
) -> BackgroundJob:
    async with sessions() as db:
        job = await db.get(BackgroundJob, job_id)
    assert job is not None
    return job


async def _until_status(
    sessions: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
    job_id: UUID,
    *statuses: str,
) -> BackgroundJob:
    deadline = asyncio.get_running_loop().time() + PATIENCE
    while True:
        job = await _job(sessions, job_id)
        if job.status in statuses:
            return job
        assert asyncio.get_running_loop().time() < deadline, f"still {job.status}: {job.last_error}"
        await asyncio.sleep(0.1)


async def _until(predicate: Callable[[], bool]) -> None:
    deadline = asyncio.get_running_loop().time() + PATIENCE
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.05)


async def test_a_job_runs_and_is_recorded_done_and_the_worker_says_it_is_alive(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"])
        job = await _until_status(sessions, job_id, "succeeded")
        await _until(lambda: (tmp_path / "alive").exists())
        async with sessions() as db:
            workers = (await db.execute(select(BackgroundWorker))).scalars().all()
    assert (job.attempts, job.last_error) == (1, None)
    assert [(worker.id, worker.pools) for worker in workers] == [("test-worker", ["system"])]
    async with sessions() as db:
        assert (await db.execute(select(BackgroundWorker))).scalars().all() == [], (
            "a worker that stops cleanly takes its row with it"
        )


async def test_what_a_job_finishes_with_is_kept_on_its_row(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["answer"], Note(text="forty-two"))
        job = await _until_status(sessions, job_id, "succeeded")
    assert job.result == {"text": "forty-two"}


async def test_a_failing_job_is_retried_and_left_dead_with_its_error(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["fail"], Note(text="the provider said no"))
        job = await _until_status(sessions, job_id, "dead")
    assert job.attempts == 2
    assert job.last_error is not None
    assert job.last_error.startswith("RuntimeError: the provider said no")


async def test_a_parse_that_eats_memory_dies_twice_and_stops_while_other_work_flows(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """The OOM loop that took the old Celery deployment down, run against the real thing."""
    async with running(sessions, tmp_path, pauses, ingest=True):
        hog = await _enqueue(sessions, INGEST_TASKS["hog"])
        ordinary = [await _enqueue(sessions, SYSTEM_TASKS["ok"]) for _ in range(5)]
        job = await _until_status(sessions, hog, "dead")
        for job_id in ordinary:
            await _until_status(sessions, job_id, "succeeded")
        after = await _enqueue(sessions, INGEST_TASKS["ok"])
        await _until_status(sessions, after, "succeeded")
    assert job.attempts == 2, "two attempts, both spent on a death, and not a third"
    assert job.last_error is not None
    assert "memory watchdog" in job.last_error
    assert "attempt 2 of 2" in job.last_error
    assert pauses == []
    # Its document would read `processing` for good: the dead child never got to
    # its own cleanup, so the worker hands the ending on, once, after the death.
    (ending,) = [end for end in ENDED if end[0] == INGEST_TASKS["hog"].kind]
    assert "memory watchdog" in ending[1]


async def test_a_child_the_kernel_kills_is_written_down_as_killed(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses, ingest=True):
        job_id = await _enqueue(sessions, INGEST_TASKS["suicide"])
        job = await _until_status(sessions, job_id, "dead")
    assert job.attempts == 1
    assert job.last_error is not None
    assert "killed by SIGKILL" in job.last_error
    ((kind, why),) = ENDED
    assert kind == INGEST_TASKS["suicide"].kind
    assert "killed by SIGKILL" in why


async def test_a_kind_that_keeps_killing_its_workers_is_paused_and_the_owner_told_once(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses, ingest=True, breaker_deaths=3):
        killers = [await _enqueue(sessions, INGEST_TASKS["suicide"]) for _ in range(3)]
        for job_id in killers:
            await _until_status(sessions, job_id, "dead")
        waiting = await _enqueue(sessions, INGEST_TASKS["suicide"])
        healthy = await _enqueue(sessions, INGEST_TASKS["ok"])
        await _until_status(sessions, healthy, "succeeded")
        assert (await _job(sessions, waiting)).status == "queued", "a paused kind is not claimed"

    assert [kind for kind, _ in pauses] == ["test-suicide"]
    async with sessions() as db:
        state = await _breaker(db, "test-suicide")
    assert state is not None
    assert state.paused_at is not None
    assert state.consecutive_deaths == 3


async def test_a_job_that_finishes_ends_its_kinds_run_of_deaths(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """Die, finish, die: never two deaths in a row, so a threshold of two never trips."""
    async with running(sessions, tmp_path, pauses, ingest=True, breaker_deaths=2):
        for text_ in ("die", "live", "die"):
            job_id = await _enqueue(sessions, INGEST_TASKS["flaky"], Note(text=text_))
            await _until_status(sessions, job_id, "dead", "succeeded")
    async with sessions() as db:
        state = await _breaker(db, "test-flaky")
    assert pauses == []
    assert state is not None
    assert (state.paused_at, state.consecutive_deaths) == (None, 1)


async def test_a_job_whose_worker_vanished_is_taken_over_by_a_worker_with_another_name(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """A deploy recreates the container: the dead worker's id is never seen again."""
    job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"])
    async with sessions() as db:
        claimed = await job_repo.claim(
            db, pool="system", worker_id="old-container:1", lease=timedelta(seconds=1)
        )
    assert claimed is not None

    async with running(sessions, tmp_path, pauses, worker_id="new-container:1"):
        job = await _until_status(sessions, job_id, "succeeded")
    assert job.attempts == 2
    assert job.worker_id == "new-container:1"


async def test_a_shutdown_mid_job_puts_it_back_with_the_attempt_spent(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """It ran, and what it did happened: the next worker gets its next attempt."""
    marker = tmp_path / "started"
    async with running(sessions, tmp_path, pauses, drain_timeout=0.2):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"], Note(seconds=30, marker=str(marker)))
        await _until(marker.exists)
    job = await _job(sessions, job_id)
    assert (job.status, job.attempts, job.worker_id) == ("queued", 1, None)
    assert job.last_error is not None
    assert job.last_error.startswith("the worker stopped while it ran (attempt 1 of ")


async def test_a_shutdown_lets_a_short_job_finish(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    marker = tmp_path / "started"
    async with running(sessions, tmp_path, pauses, drain_timeout=10):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"], Note(seconds=0.5, marker=str(marker)))
        await _until(marker.exists)
    assert (await _job(sessions, job_id)).status == "succeeded"


async def test_a_job_past_its_timeout_is_failed_each_attempt_and_then_dead(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with running(sessions, tmp_path, pauses):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["slow"], Note(seconds=30))
        job = await _until_status(sessions, job_id, "dead")
    assert job.attempts == 3
    assert job.last_error is not None
    assert job.last_error.startswith("timed out after 0:00:01")


async def test_a_job_of_an_undeclared_kind_is_dead_at_once(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    async with sessions() as db:
        job_id = await job_repo.add(
            db, kind="retired-kind", pool="system", payload={}, max_attempts=3, priority=1
        )
    assert job_id is not None
    async with running(sessions, tmp_path, pauses):
        job = await _until_status(sessions, job_id, "dead")
    assert job.attempts == 1
    assert job.last_error == "no task is declared for the job kind 'retired-kind'"


async def test_a_worker_whose_database_goes_away_backs_off_and_carries_on(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """Twenty refused connections, then the database is back: no hot loop, no lost job."""
    calls = 0
    refused = 20

    @asynccontextmanager
    async def flaky() -> AsyncIterator[AsyncSession]:
        nonlocal calls
        calls += 1
        if calls <= refused:
            raise ConnectionRefusedError("the database is restarting")
        async with sessions() as db:
            yield db

    job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"])
    started = asyncio.get_running_loop().time()
    async with running(flaky, tmp_path, pauses):
        await _until_status(sessions, job_id, "succeeded")
    elapsed = asyncio.get_running_loop().time() - started
    assert calls > refused
    assert elapsed > 1.0, "twenty failures were spread out, not spun through"


async def test_a_worker_that_lost_its_lease_counts_the_possible_duplicate(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]]
) -> None:
    """While the job runs, another worker takes it over; the first run's ending is refused and counted."""
    marker = tmp_path / "started"
    async with running(sessions, tmp_path, pauses):
        job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"], Note(seconds=1, marker=str(marker)))
        await _until(marker.exists)
        async with sessions() as db:
            await db.execute(
                text(
                    "UPDATE background_jobs SET attempts = attempts + 1, worker_id = 'other' "
                    "WHERE id = :id"
                ),
                {"id": job_id},
            )
        await _until_lease_lost(sessions)
    job = await _job(sessions, job_id)
    assert (job.status, job.worker_id, job.attempts) == ("running", "other", 2)


async def _breaker(db: AsyncSession, kind: str) -> BackgroundTaskKind | None:
    """The deployment-wide breaker of `kind`: these jobs belong to no organization."""
    found = await kind_repo.get(db, kind, None)
    return None if found is None else found[0]


async def _until_lease_lost(
    sessions: Callable[[], contextlib.AbstractAsyncContextManager[AsyncSession]],
) -> None:
    deadline = asyncio.get_running_loop().time() + PATIENCE
    while True:
        async with sessions() as db:
            state = await _breaker(db, "test-ok")
        if state is not None and state.lease_lost == 1:
            return
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.1)


async def test_a_committed_job_wakes_the_worker_without_waiting_for_the_poll(
    sessions, tmp_path: Path, pauses: list[tuple[str, str]], schema_url: str
) -> None:
    async with running(
        sessions, tmp_path, pauses, poll_every=60, listen_dsn=asyncpg_dsn(schema_url)
    ):
        await asyncio.sleep(1.0)
        started = asyncio.get_running_loop().time()
        job_id = await _enqueue(sessions, SYSTEM_TASKS["ok"])
        await _until_status(sessions, job_id, "succeeded")
        assert asyncio.get_running_loop().time() - started < 10
