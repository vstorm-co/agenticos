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
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models.background_job import BackgroundJob
from app.db.models.organization import Organization
from app.db.models.user import User
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
    organization_id: UUID | None = None,
) -> UUID:
    async with sessions() as db, db.begin():
        job_id = await job_repo.add(
            db,
            kind=kind,
            pool=pool,
            payload={},
            max_attempts=max_attempts,
            priority=1,
            organization_id=organization_id,
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
        assert await job_repo.release(db, job_id, fence=first.attempts) is None
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


async def test_a_job_stopped_under_a_shutdown_keeps_its_attempt_spent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """It ran, and what it did happened: a one-attempt job is not started again."""
    job_id = await _queue(sessions, max_attempts=1)
    claimed = await _claim(sessions)
    assert claimed is not None

    async with sessions() as db, db.begin():
        assert await job_repo.release(db, job_id, fence=claimed.attempts) == "dead"
    job = await _status(sessions, job_id)
    assert (job.status, job.attempts) == ("dead", 1)
    assert job.last_error == "the worker stopped while it ran (attempt 1 of 1)"
    assert job.finished_at is not None
    assert await _claim(sessions) is None


async def test_a_job_with_attempts_left_goes_back_after_a_shutdown(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=2)
    claimed = await _claim(sessions)
    assert claimed is not None

    async with sessions() as db, db.begin():
        assert await job_repo.release(db, job_id, fence=claimed.attempts) == "queued"
    job = await _status(sessions, job_id)
    assert (job.status, job.attempts, job.finished_at) == ("queued", 1, None)
    again = await _claim(sessions)
    assert again is not None and again.attempts == 2


async def test_a_job_claimed_but_never_started_gets_its_attempt_back(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=1)
    claimed = await _claim(sessions)
    assert claimed is not None

    async with sessions() as db, db.begin():
        assert await job_repo.unclaim(db, job_id, fence=claimed.attempts) is True
        assert await job_repo.unclaim(db, job_id, fence=claimed.attempts) is False
    job = await _status(sessions, job_id)
    assert (job.status, job.attempts, job.started_at) == ("queued", 0, None)


async def _running_with_a_newer_copy_queued(
    sessions: async_sessionmaker[AsyncSession], *, max_attempts: int = 3
) -> tuple[UUID, int]:
    """A keyed job running while a newer copy waits under the same key."""
    first = await _queue(sessions, dedupe_key="sync:9", max_attempts=max_attempts)
    claimed = await _claim(sessions)
    assert claimed is not None and claimed.id == first
    await _queue(sessions, dedupe_key="sync:9")
    return first, claimed.attempts


async def test_a_failed_attempt_with_a_newer_copy_queued_is_withdrawn_not_requeued(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Codex on #2248: putting it back was a unique violation that wedged the source."""
    job_id, fence = await _running_with_a_newer_copy_queued(sessions)

    async with sessions() as db, db.begin():
        outcome = await job_repo.fail(db, job_id, fence=fence, error="boom", retry_in=timedelta(0))

    assert outcome is FailOutcome.SUPERSEDED
    job = await _status(sessions, job_id)
    assert job.status == "cancelled" and job.finished_at is not None


async def test_a_shutdown_with_a_newer_copy_queued_withdraws_the_old_one(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id, fence = await _running_with_a_newer_copy_queued(sessions)

    async with sessions() as db, db.begin():
        assert await job_repo.release(db, job_id, fence=fence) == "cancelled"


async def test_a_lapsed_lease_with_a_newer_copy_queued_is_withdrawn_and_says_what_it_carried(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await _queue(sessions, dedupe_key="sync:10")
    claimed = await _claim(sessions, lease=EXPIRED)
    assert claimed is not None
    await _queue(sessions, dedupe_key="sync:10")

    async with sessions() as db, db.begin():
        rescued = await job_repo.rescue_expired(db, retry_in=timedelta(0))

    (job,) = [r for r in rescued if r.id == first]
    assert (job.status, job.dead, job.organization_id) == ("cancelled", False, None)


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


async def test_two_enqueuers_of_an_active_key_are_decided_one_at_a_time(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The second waits for the first to commit, then sees its row - not a gap to insert into."""

    async def add(db: AsyncSession) -> UUID | None:
        return await job_repo.add(
            db,
            kind="probe",
            pool="system",
            payload={},
            max_attempts=1,
            priority=1,
            dedupe_key="sync:race",
            dedupe_active=True,
        )

    async with sessions() as first_db:
        async with first_db.begin():
            first = await add(first_db)
            assert first is not None

            async def second() -> UUID | None:
                async with sessions() as db, db.begin():
                    return await add(db)

            racing = asyncio.create_task(second())
            await asyncio.sleep(0.3)
            assert not racing.done(), "the second enqueuer read before the first committed"
        # Committed; the first copy is claimed at once, so only `running` holds the key.
        await _claim(sessions)

    assert await racing is None


async def test_a_queued_payload_can_be_rewritten_until_a_worker_claims_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, dedupe_key="sync:adopt")
    async with sessions() as db, db.begin():
        latest = await job_repo.latest_with_dedupe_key(db, "sync:adopt")
        assert latest is not None and latest.id == job_id
        assert await job_repo.latest_with_dedupe_key(db, "sync:nothing") is None
        assert await job_repo.replace_queued_payload(db, job_id, {"log": "mine"}) is True
    assert (await _status(sessions, job_id)).payload == {"log": "mine"}

    await _claim(sessions)
    async with sessions() as db, db.begin():
        assert await job_repo.replace_queued_payload(db, job_id, {"log": "late"}) is False
    assert (await _status(sessions, job_id)).payload == {"log": "mine"}


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
        assert await kind_repo.pause(db, "hog", None, reason="five deaths in a row") is True
        assert await kind_repo.pause(db, "hog", None, reason="again") is False
    assert await _claim(sessions) is None

    async with sessions() as db, db.begin():
        assert await kind_repo.resume(db, "hog", None) is True
    assert await _claim(sessions) is not None


async def _organization(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions() as db, db.begin():
        founder = User(
            id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True
        )
        db.add(founder)
        await db.flush()
        organization = Organization(
            id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex[:8]}", created_by_user_id=founder.id
        )
        db.add(organization)
    return organization.id


async def test_a_kind_paused_for_one_organization_is_still_claimed_for_another(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One tenant whose jobs keep killing their worker pauses the kind for itself,
    not for every organization on the deployment (Codex, #2248)."""
    noisy, quiet = await _organization(sessions), await _organization(sessions)
    held = await _queue(sessions, kind="hog", organization_id=noisy)
    served = await _queue(sessions, kind="hog", organization_id=quiet)
    async with sessions() as db, db.begin():
        assert await kind_repo.pause(db, "hog", noisy, reason="five deaths in a row") is True

    claimed = await _claim(sessions)
    assert claimed is not None and claimed.id == served
    assert await _claim(sessions) is None

    async with sessions() as db, db.begin():
        assert await kind_repo.resume(db, "hog", noisy) is True
    claimed = await _claim(sessions)
    assert claimed is not None and claimed.id == held


async def test_a_kind_paused_for_the_whole_deployment_is_claimed_for_nobody(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    organization = await _organization(sessions)
    await _queue(sessions, kind="hog", organization_id=organization)
    await _queue(sessions, kind="hog")
    async with sessions() as db, db.begin():
        assert await kind_repo.pause(db, "hog", None, reason="by hand") is True
        # Two scopes of one kind, each its own row.
        assert await kind_repo.record_death(db, "hog", organization) == 1
        assert await kind_repo.record_death(db, "hog", None) == 1

    assert await _claim(sessions) is None


async def test_a_deleted_organizations_job_is_not_counted_and_does_not_break_its_rescue(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A job keeps its organization's id after the organization is gone - the purge
    queues clean-up under it - and the breaker's row has a foreign key to it. An
    insert the key refused rolled back the rescue it was part of, leaving the job
    `running` on every pass (Codex, #2248). Nothing is counted for it instead."""
    gone = await _organization(sessions)
    async with sessions() as db, db.begin():
        await db.execute(delete(Organization).where(Organization.id == gone))

    async with sessions() as db, db.begin():
        assert await kind_repo.record_death(db, "hog", gone) == 0
        await kind_repo.record_lease_lost(db, "hog", gone)
        assert await kind_repo.pause(db, "hog", gone, reason="five deaths in a row") is False
        # The same transaction still commits a deployment-wide count beside them.
        assert await kind_repo.record_death(db, "hog", None) == 1

    async with sessions() as db:
        kinds = await kind_repo.list_all(db)
    assert [(kind.kind, kind.organization_id) for kind, _name in kinds if kind.kind == "hog"] == [
        ("hog", None)
    ]


async def test_an_end_is_owed_its_settlement_until_it_is_marked_and_owed_again_after_a_retry(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _queue(sessions, max_attempts=1)
    claimed = await _claim(sessions)
    assert claimed is not None
    async with sessions() as db, db.begin():
        assert await job_repo.bury(db, job_id, fence=claimed.attempts, error="no such kind")

    async with sessions() as db, db.begin():
        owed = [end for end in await job_repo.unsettled_ends(db) if end.id == job_id]
        assert [(end.kind, end.why) for end in owed] == [("probe", "no such kind")]
        await job_repo.mark_settled(db, job_id)
        assert job_id not in [end.id for end in await job_repo.unsettled_ends(db)]
        assert await job_repo.requeue_dead(db, job_id) is True

    assert (await _status(sessions, job_id)).settled_at is None


async def test_a_settlement_is_claimed_by_one_caller_and_released_by_a_rollback(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """#2334: the worker that saw a death and a rescuer reading it as owed both
    reach for its settlement; the row lock lets exactly one run the settler."""
    job_id = await _queue(sessions, max_attempts=1)
    claimed = await _claim(sessions)
    assert claimed is not None
    async with sessions() as db, db.begin():
        assert await job_repo.bury(db, job_id, fence=claimed.attempts, error="no such kind")

    async with sessions() as first:
        assert await job_repo.claim_settlement(first, job_id=job_id) is True
        async with sessions() as second, second.begin():
            # Held by the first: skipped, not waited for.
            assert await job_repo.claim_settlement(second, job_id=job_id) is False
        await first.rollback()

    # A settler that failed leaves the end owed, for the next pass.
    async with sessions() as db, db.begin():
        assert await job_repo.claim_settlement(db, job_id=job_id) is True
        await job_repo.mark_settled(db, job_id)

    async with sessions() as db, db.begin():
        assert await job_repo.claim_settlement(db, job_id=job_id) is False


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


async def test_workspace_progress_and_activation_reject_expired_cancelled_and_reclaimed_attempts(
    sessions,
) -> None:
    job_id = await _queue(sessions)
    async with sessions() as db, db.begin():
        job = await db.get(BackgroundJob, job_id)
        job.status = "running"
        job.attempts = 1
        job.lease_until = datetime.now(UTC) + LEASE
    async with sessions() as db, db.begin():
        assert await job_repo.workspace_move_progress(
            db, job_id, attempt=1, result={"copied_files": 2}
        )
        assert await job_repo.lock_workspace_attempt(db, job_id, attempt=1) is not None
        assert not await job_repo.workspace_move_progress(
            db, job_id, attempt=2, result={"copied_files": 100}
        )
        assert await job_repo.lock_workspace_attempt(db, job_id, attempt=2) is None
    for status, expires in (("cancelled", LEASE), ("running", EXPIRED)):
        async with sessions() as db, db.begin():
            job = await db.get(BackgroundJob, job_id)
            job.status = status
            job.lease_until = datetime.now(UTC) + expires
        async with sessions() as db, db.begin():
            assert not await job_repo.workspace_move_progress(
                db, job_id, attempt=1, result={"copied_files": 100}
            )
            assert await job_repo.lock_workspace_attempt(db, job_id, attempt=1) is None
            assert (await db.get(BackgroundJob, job_id)).result == {"copied_files": 2}
