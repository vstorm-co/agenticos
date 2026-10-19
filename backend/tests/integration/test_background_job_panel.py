"""What the deployment's owner sees and does on the Background jobs page (#2219).

Against the real tables, because the page's promises are the queue's: a retry
gives a dead job fresh attempts and only a dead one, a cancel withdraws a job
nobody started and only that, a resumed kind is claimed again - and each of
them leaves an audit entry naming who did it.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.audit_log import AppAdminAuditLog
from app.repositories import background_job as job_repo
from app.repositories import background_schedule as schedule_repo
from app.repositories import background_worker as worker_repo
from app.services.background_jobs import BackgroundJobService

pytestmark = pytest.mark.anyio

ADMIN = uuid4()


async def _job(db: AsyncSession, *, kind: str = "expire-approvals", max_attempts: int = 1):
    job_id = await job_repo.add(
        db, kind=kind, pool="system", payload={}, max_attempts=max_attempts, priority=1
    )
    assert job_id is not None
    return job_id


async def _dead(db: AsyncSession):
    job_id = await _job(db)
    claimed = await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(seconds=-1))
    assert claimed is not None
    await job_repo.rescue_expired(db, retry_in=timedelta(0))
    return job_id


async def _audited(db: AsyncSession) -> list[tuple[str, str | None]]:
    rows = (await db.execute(select(AppAdminAuditLog))).scalars().all()
    return [(row.action, row.target_id) for row in rows]


async def test_the_overview_counts_every_status_and_lists_who_is_alive(db: AsyncSession) -> None:
    await _job(db)
    await _dead(db)
    await worker_repo.beat(db, worker_id="host:1:abc", hostname="host", pools=["system"])
    await schedule_repo.declare(
        db,
        name="expire-approvals",
        kind="expire-approvals",
        interval_seconds=3600,
        overlap="skip",
        misfire="latest",
        grace_seconds=60,
        now=datetime.now(UTC),
        first_run_at=datetime.now(UTC),
    )

    overview = await BackgroundJobService(db).overview()

    assert overview.counts == {"queued": 1, "running": 0, "succeeded": 0, "dead": 1, "cancelled": 0}
    assert [worker.id for worker in overview.workers] == ["host:1:abc"]
    assert [schedule.name for schedule in overview.schedules] == ["expire-approvals"]
    assert overview.kinds == []


async def test_the_listing_pages_through_jobs_queued_in_one_transaction(db: AsyncSession) -> None:
    """They share one `created_at`: a cursor on the time alone would lose all but the first page."""
    ids = [await _job(db) for _ in range(3)]
    await _job(db, kind="reap-stale-runs")
    service = BackgroundJobService(db)

    first = await service.list_jobs(kind="expire-approvals", limit=2)
    assert len(first.items) == 2
    assert first.next_before is not None
    assert first.next_before_id is not None
    rest = await service.list_jobs(
        kind="expire-approvals", limit=2, before=(first.next_before, first.next_before_id)
    )

    listed = [item.id for item in first.items + rest.items]
    assert sorted(listed) == sorted(ids)
    assert rest.next_before is None
    assert [item.kind for item in (await service.list_jobs(status="queued")).items].count(
        "reap-stale-runs"
    ) == 1


async def test_retrying_a_dead_job_requeues_it_and_audits_the_owner(db: AsyncSession) -> None:
    job_id = await _dead(db)

    retried = await BackgroundJobService(db).retry(job_id, actor_user_id=ADMIN)

    assert (retried.status, retried.attempts) == ("queued", 0)
    assert ("background_job.retried", str(job_id)) in await _audited(db)


async def test_only_a_dead_job_can_be_retried(db: AsyncSession) -> None:
    job_id = await _job(db)

    with pytest.raises(BadRequestError, match="Only a dead job can be retried; this one is queued"):
        await BackgroundJobService(db).retry(job_id, actor_user_id=ADMIN)
    with pytest.raises(NotFoundError):
        await BackgroundJobService(db).retry(uuid4(), actor_user_id=ADMIN)
    assert await _audited(db) == []


async def test_cancelling_withdraws_a_queued_job_and_refuses_a_running_one(
    db: AsyncSession,
) -> None:
    queued = await _job(db)
    service = BackgroundJobService(db)

    cancelled = await service.cancel(queued, actor_user_id=ADMIN)
    assert cancelled.status == "cancelled"
    assert ("background_job.cancelled", str(queued)) in await _audited(db)

    running = await _job(db)
    await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1))
    with pytest.raises(BadRequestError, match="this one is running"):
        await service.cancel(running, actor_user_id=ADMIN)
    with pytest.raises(NotFoundError):
        await service.cancel(uuid4(), actor_user_id=ADMIN)


async def test_a_kind_paused_by_hand_stops_being_claimed_until_resumed(db: AsyncSession) -> None:
    await _job(db)
    service = BackgroundJobService(db)

    paused = await service.pause_kind("expire-approvals", reason="upgrading", actor_user_id=ADMIN)
    assert paused.paused_reason == "upgrading"
    again = await service.pause_kind("expire-approvals", reason="twice", actor_user_id=ADMIN)
    assert again.paused_reason == "upgrading", "pausing a paused kind changes nothing"
    assert (
        await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1)) is None
    )

    resumed = await service.resume_kind("expire-approvals", actor_user_id=ADMIN)
    assert resumed.paused_at is None
    assert await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1))
    assert [action for action, _ in await _audited(db)] == [
        "background_kind.paused",
        "background_kind.resumed",
    ]


async def test_resuming_a_kind_that_is_not_paused_is_refused(db: AsyncSession) -> None:
    with pytest.raises(BadRequestError, match="not paused"):
        await BackgroundJobService(db).resume_kind("expire-approvals", actor_user_id=ADMIN)


async def test_an_unknown_kind_cannot_be_paused_or_resumed(db: AsyncSession) -> None:
    service = BackgroundJobService(db)
    with pytest.raises(NotFoundError):
        await service.pause_kind("no-such-kind", reason="x", actor_user_id=ADMIN)
    with pytest.raises(NotFoundError):
        await service.resume_kind("no-such-kind", actor_user_id=ADMIN)


async def test_a_kind_that_never_died_reads_as_untouched(db: AsyncSession) -> None:
    await BackgroundJobService(db).pause_kind("reap-stale-runs", reason="x", actor_user_id=ADMIN)
    resumed = await BackgroundJobService(db).resume_kind("reap-stale-runs", actor_user_id=ADMIN)
    assert (resumed.consecutive_deaths, resumed.lease_lost) == (0, 0)
