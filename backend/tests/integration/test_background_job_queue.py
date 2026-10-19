"""The queue's guarantees, asked of Postgres rather than of a mock (#2219).

Each test names a guarantee the worker relies on: an attempt is spent at the
claim, so a job that kills its worker reaches `dead` instead of looping; a
worker that lost its lease cannot overwrite the job's next holder; two claims
never hand out one job; a rolled-back change queues nothing.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.background_job import BackgroundJob
from app.repositories import background_job as job_repo
from app.repositories import background_task_kind as kind_repo
from app.repositories.background_job import FailOutcome
from app.services.background_jobs import enqueue
from app.worker.jobs import INGEST_DOCUMENT, REAP_STALE_RUNS, IngestDocument, Tick

pytestmark = pytest.mark.anyio

LEASE = timedelta(seconds=60)
EXPIRED = timedelta(seconds=-1)
"""A lease that has already run out the moment it is granted: a worker that died at once."""


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _queue(
    sessions: async_sessionmaker[AsyncSession],
    kind: str = "probe",
    *,
    pool: str = "system",
    max_attempts: int = 3,
    dedupe_key: str | None = None,
    concurrency_key: str | None = None,
) -> UUID:
    async with sessions() as db, db.begin():
        job_id = await job_repo.add(
            db,
            kind=kind,
            pool=pool,
            payload={},
            max_attempts=max_attempts,
            priority=1,
            dedupe_key=dedupe_key,
            concurrency_key=concurrency_key,
        )
    assert job_id is not None
    return job_id


async def _status(sessions: async_sessionmaker[AsyncSession], job_id: UUID) -> BackgroundJob:
    async with sessions() as db:
        job = await db.get(BackgroundJob, job_id)
    assert job is not None
    return job


async def _claim(
    sessions: async_sessionmaker[AsyncSession],
    *,
    worker: str = "w1",
    lease: timedelta = LEASE,
    pool: str = "system",
) -> job_repo.ClaimedJob | None:
    async with sessions() as db, db.begin():
        return await job_repo.claim(db, pool=pool, worker_id=worker, lease=lease)


async def _rescue(sessions: async_sessionmaker[AsyncSession]) -> list[job_repo.RescuedJob]:
    async with sessions() as db, db.begin():
        return await job_repo.rescue_expired(db, retry_in=timedelta(0))


async def test_a_job_that_kills_its_worker_is_dead_after_its_attempts_and_never_handed_out_again(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The OOM loop, end to end: claim, die, rescue - three times - then nothing.

    The worker never reports anything: each claim's lease simply runs out, the
    way it does when the kernel kills the process holding the job.
    """
    job_id = await _queue(sessions, max_attempts=3)

    for attempt in (1, 2, 3):
        claimed = await _claim(sessions, lease=EXPIRED)
        assert claimed is not None
        assert claimed.attempts == attempt
        rescued = await _rescue(sessions)
        assert [(r.id, r.dead) for r in rescued] == [(job_id, attempt == 3)]

    assert await _claim(sessions) is None
    job = await _status(sessions, job_id)
    assert job.status == "dead"
    assert job.attempts == 3
    assert job.finished_at is not None
    assert job.last_error is not None
    assert "worker lost" in job.last_error
    assert "attempt 3 of 3" in job.last_error


async def test_the_rescued_error_names_the_worker_that_died(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions)
    await _claim(sessions, worker="host-a:123", lease=EXPIRED)
    await _rescue(sessions)

    job = await _status(sessions, job_id)
    assert job.status == "queued"
    assert job.worker_id is None
    assert job.last_error is not None
    assert "host-a:123" in job.last_error


async def test_a_live_lease_is_not_rescued(sessions: async_sessionmaker[AsyncSession]) -> None:
    job_id = await _queue(sessions)
    await _claim(sessions, lease=LEASE)

    assert await _rescue(sessions) == []
    assert (await _status(sessions, job_id)).status == "running"


async def test_a_worker_that_lost_its_lease_cannot_settle_the_next_holders_job(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Worker A stalls past its lease, B takes the job over; A's late writes match nothing."""
    job_id = await _queue(sessions)
    first = await _claim(sessions, worker="a", lease=EXPIRED)
    assert first is not None
    await _rescue(sessions)
    second = await _claim(sessions, worker="b")
    assert second is not None
    assert second.attempts == 2

    async with sessions() as db, db.begin():
        assert await job_repo.complete(db, job_id, fence=first.attempts) is False
        outcome = await job_repo.fail(
            db, job_id, fence=first.attempts, error="late", retry_in=timedelta(0)
        )
        assert outcome is FailOutcome.LOST
        assert await job_repo.release(db, job_id, fence=first.attempts) is False
    assert (await _status(sessions, job_id)).worker_id == "b"

    async with sessions() as db, db.begin():
        assert await job_repo.complete(db, job_id, fence=second.attempts) is True
    assert (await _status(sessions, job_id)).status == "succeeded"


async def test_two_claims_at_once_never_hand_out_the_same_job(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The first claim holds its row locked in an open transaction; the second skips it."""
    first_id = await _queue(sessions)
    second_id = await _queue(sessions)

    async with sessions() as holding, holding.begin():
        held = await job_repo.claim(holding, pool="system", worker_id="a", lease=LEASE)
        assert held is not None
        other = await _claim(sessions, worker="b")
        assert other is not None
        assert {held.id, other.id} == {first_id, second_id}
        assert await _claim(sessions, worker="c") is None


async def test_many_concurrent_claims_hand_out_each_job_exactly_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    queued = {await _queue(sessions) for _ in range(20)}

    async def drain(worker: str) -> list[UUID]:
        taken: list[UUID] = []
        while (claimed := await _claim(sessions, worker=worker)) is not None:
            taken.append(claimed.id)
        return taken

    results = await asyncio.gather(*(drain(f"w{n}") for n in range(5)))
    taken = [job_id for batch in results for job_id in batch]
    assert sorted(taken) == sorted(queued)


async def test_a_rolled_back_change_queues_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as db:
        await db.begin()
        payload = IngestDocument(
            rag_document_id=uuid4(),
            collection_name="docs",
            filepath="media/_rag_tmp/x.pdf",
            source_path="x.pdf",
            replace=False,
            attempt=1,
        )
        assert await enqueue(db, INGEST_DOCUMENT, payload) is not None
        await db.rollback()

    async with sessions() as db:
        assert (await db.execute(select(BackgroundJob))).scalars().all() == []


async def test_enqueue_writes_the_tasks_pool_attempts_and_a_payload_that_reads_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    payload = IngestDocument(
        rag_document_id=uuid4(),
        collection_name="docs",
        filepath="media/_rag_tmp/x.pdf",
        source_path="x.pdf",
        replace=True,
        attempt=2,
    )
    async with sessions() as db, db.begin():
        job_id = await enqueue(db, INGEST_DOCUMENT, payload)
    assert job_id is not None

    job = await _status(sessions, job_id)
    assert (job.kind, job.pool, job.max_attempts, job.priority) == (
        "ingest-document",
        "ingest",
        2,
        0,
    )
    assert INGEST_DOCUMENT.load(job.payload) == payload


async def test_a_failure_retries_after_its_backoff_and_the_last_one_is_dead(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=2)

    claimed = await _claim(sessions)
    assert claimed is not None
    async with sessions() as db, db.begin():
        outcome = await job_repo.fail(
            db, job_id, fence=claimed.attempts, error="boom", retry_in=timedelta(hours=1)
        )
    assert outcome is FailOutcome.RETRYING
    assert await _claim(sessions) is None, "the backoff has not ended"

    async with sessions() as db, db.begin():
        await db.execute(
            text("UPDATE background_jobs SET run_after = now() WHERE id = :id"), {"id": job_id}
        )
    claimed = await _claim(sessions)
    assert claimed is not None
    async with sessions() as db, db.begin():
        outcome = await job_repo.fail(
            db, job_id, fence=claimed.attempts, error="boom again", retry_in=timedelta(0)
        )
    assert outcome is FailOutcome.DEAD
    job = await _status(sessions, job_id)
    assert (job.status, job.last_error) == ("dead", "boom again")


async def test_a_released_job_gets_its_attempt_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=1)
    claimed = await _claim(sessions)
    assert claimed is not None

    async with sessions() as db, db.begin():
        assert await job_repo.release(db, job_id, fence=claimed.attempts) is True
    job = await _status(sessions, job_id)
    assert (job.status, job.attempts) == ("queued", 0)
    assert await _claim(sessions) is not None


async def test_a_second_enqueue_with_a_queued_dedupe_key_is_dropped(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await _queue(sessions, dedupe_key="sync:1")
    async with sessions() as db, db.begin():
        assert (
            await job_repo.add(
                db,
                kind="probe",
                pool="system",
                payload={},
                max_attempts=1,
                priority=1,
                dedupe_key="sync:1",
            )
            is None
        )

    # Once it runs, a key that dedupes on queued copies only lets one more wait...
    await _claim(sessions)
    assert (await _status(sessions, first)).status == "running"
    waiting = await _queue(sessions, dedupe_key="sync:1")
    assert waiting != first

    # ...and one that dedupes on active copies does not.
    async with sessions() as db, db.begin():
        assert (
            await job_repo.add(
                db,
                kind="probe",
                pool="system",
                payload={},
                max_attempts=1,
                priority=1,
                dedupe_key="sync:1",
                dedupe_active=True,
            )
            is None
        )


async def test_jobs_sharing_a_concurrency_key_run_one_at_a_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await _queue(sessions, concurrency_key="trigger:1")
    second = await _queue(sessions, concurrency_key="trigger:1")
    unrelated = await _queue(sessions)

    running = await _claim(sessions)
    assert running is not None
    assert running.id == first
    next_up = await _claim(sessions)
    assert next_up is not None
    assert next_up.id == unrelated, "the second keyed job waits for the first"
    assert await _claim(sessions) is None

    async with sessions() as db, db.begin():
        await job_repo.complete(db, first, fence=running.attempts)
    after = await _claim(sessions)
    assert after is not None
    assert after.id == second


async def test_a_paused_kind_is_not_claimed_until_resumed(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _queue(sessions, kind="hog")
    async with sessions() as db, db.begin():
        assert await kind_repo.pause(db, "hog", reason="five deaths in a row") is True
        assert await kind_repo.pause(db, "hog", reason="again") is False
    assert await _claim(sessions) is None

    async with sessions() as db, db.begin():
        assert await kind_repo.resume(db, "hog") is True
    assert await _claim(sessions) is not None


async def test_the_claim_takes_the_lowest_priority_first_then_the_oldest(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as db, db.begin():
        bulk = await job_repo.add(
            db, kind="b", pool="system", payload={}, max_attempts=1, priority=2
        )
        old = await job_repo.add(
            db, kind="s", pool="system", payload={}, max_attempts=1, priority=1
        )
    async with sessions() as db, db.begin():
        interactive = await job_repo.add(
            db, kind="i", pool="system", payload={}, max_attempts=1, priority=0
        )
        newer = await job_repo.add(
            db, kind="s", pool="system", payload={}, max_attempts=1, priority=1
        )

    order = []
    while (claimed := await _claim(sessions)) is not None:
        order.append(claimed.id)
    assert order == [interactive, old, newer, bulk]


async def test_a_pool_claims_only_its_own_jobs(sessions: async_sessionmaker[AsyncSession]) -> None:
    ingest = await _queue(sessions, pool="ingest")
    assert await _claim(sessions, pool="system") is None
    claimed = await _claim(sessions, pool="ingest")
    assert claimed is not None
    assert claimed.id == ingest


async def test_a_committed_enqueue_wakes_listeners_and_a_rolled_back_one_does_not(
    sessions: async_sessionmaker[AsyncSession], schema_url: str
) -> None:
    connection = await asyncpg.connect(schema_url.replace("postgresql+asyncpg", "postgresql"))
    received: asyncio.Queue[str] = asyncio.Queue()
    await connection.add_listener(
        job_repo.NOTIFY_CHANNEL, lambda *args: received.put_nowait(args[3])
    )
    try:
        async with sessions() as db:
            await db.begin()
            await job_repo.add(
                db, kind="probe", pool="agent", payload={}, max_attempts=1, priority=1
            )
            await db.rollback()
        await _queue(sessions, pool="ingest")

        assert await asyncio.wait_for(received.get(), timeout=5) == "ingest"
        assert received.empty()
    finally:
        await connection.close()


async def test_finished_jobs_older_than_the_cutoff_are_forgotten_and_live_ones_kept(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    done = await _queue(sessions)
    claimed = await _claim(sessions)
    assert claimed is not None
    async with sessions() as db, db.begin():
        await job_repo.complete(db, done, fence=claimed.attempts)
    live = await _queue(sessions)

    finished_at = (await _status(sessions, done)).finished_at
    assert finished_at is not None
    async with sessions() as db, db.begin():
        removed = await job_repo.delete_finished_before(
            db, cutoff=finished_at + timedelta(seconds=1), limit=100
        )
    assert removed == 1
    async with sessions() as db:
        remaining = (await db.execute(select(BackgroundJob.id))).scalars().all()
    assert remaining == [live]


async def test_a_dead_job_requeued_from_the_panel_gets_fresh_attempts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=1)
    await _claim(sessions, lease=EXPIRED)
    await _rescue(sessions)
    assert (await _status(sessions, job_id)).status == "dead"

    async with sessions() as db, db.begin():
        assert await job_repo.requeue_dead(db, job_id) is True
        assert await job_repo.requeue_dead(db, job_id) is False
    claimed = await _claim(sessions)
    assert claimed is not None
    assert claimed.attempts == 1


async def test_only_a_queued_job_can_be_cancelled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    queued = await _queue(sessions)
    running = await _queue(sessions)
    async with sessions() as db, db.begin():
        assert await job_repo.cancel_queued(db, queued) is True
    claimed = await _claim(sessions)
    assert claimed is not None
    assert claimed.id == running
    async with sessions() as db, db.begin():
        assert await job_repo.cancel_queued(db, running) is False
    assert (await _status(sessions, queued)).status == "cancelled"


async def test_a_schedule_with_a_job_still_running_reads_as_active(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as db, db.begin():
        await enqueue(
            db,
            REAP_STALE_RUNS,
            Tick(scheduled_for=datetime.now(UTC)),
            schedule_name="reap-stale-runs",
        )
    async with sessions() as db:
        assert await job_repo.has_active_for_schedule(db, "reap-stale-runs") is True
        assert await job_repo.has_active_for_schedule(db, "other") is False
