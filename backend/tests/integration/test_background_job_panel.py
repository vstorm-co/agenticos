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

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import background_job as job_repo
from app.repositories import background_schedule as schedule_repo
from app.repositories import background_task_kind as kind_repo
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


async def _dead_with_a_newer_copy_queued(db: AsyncSession):
    """A dead sync whose source was synced again since: the newer copy holds the key."""
    dead = await job_repo.add(
        db,
        kind="expire-approvals",
        pool="system",
        payload={},
        max_attempts=1,
        priority=1,
        dedupe_key="sync:7",
    )
    assert dead is not None
    await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(seconds=-1))
    await job_repo.rescue_expired(db, retry_in=timedelta(0))
    newer = await job_repo.add(
        db,
        kind="expire-approvals",
        pool="system",
        payload={},
        max_attempts=1,
        priority=1,
        dedupe_key="sync:7",
    )
    assert newer is not None
    return dead


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


async def test_a_retry_that_would_collide_with_newer_queued_work_is_refused(
    db: AsyncSession,
) -> None:
    dead = await _dead_with_a_newer_copy_queued(db)

    with pytest.raises(AlreadyExistsError, match="newer job for the same work"):
        await BackgroundJobService(db).retry(dead, actor_user_id=ADMIN)
    assert (await job_repo.get(db, dead)).status == "dead"  # type: ignore[union-attr]
    assert await _audited(db) == []


async def test_a_newer_copy_queued_after_the_check_is_refused_the_same_way(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check and the update race; the unique index decides, and the answer is a 409."""
    dead = await _dead_with_a_newer_copy_queued(db)

    async def missed(*_: object) -> bool:
        return False

    monkeypatch.setattr(job_repo, "queued_with_key", missed)
    with pytest.raises(AlreadyExistsError):
        await BackgroundJobService(db).retry(dead, actor_user_id=ADMIN)
    assert (await job_repo.get(db, dead)).status == "dead"  # type: ignore[union-attr]


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


async def test_a_job_whose_document_waits_on_it_cannot_be_cancelled(db: AsyncSession) -> None:
    """Cancelled, the document would read `processing` for good."""
    job_id = await _job(db, kind="ingest-document")

    with pytest.raises(BadRequestError, match="cannot be cancelled") as refused:
        await BackgroundJobService(db).cancel(job_id, actor_user_id=ADMIN)

    assert refused.value.details == {"job_id": str(job_id), "kind": "ingest-document"}
    assert (await job_repo.get(db, job_id)).status == "queued"  # type: ignore[union-attr]
    assert await _audited(db) == []


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

    resumed = await service.resume_kind(
        "expire-approvals", organization_id=None, actor_user_id=ADMIN
    )
    assert resumed.paused_at is None
    assert await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1))
    assert [action for action, _ in await _audited(db)] == [
        "background_kind.paused",
        "background_kind.resumed",
    ]


async def test_an_organizations_pause_is_listed_by_name_and_resumed_alone(
    db: AsyncSession,
) -> None:
    founder = User(id=uuid4(), email=f"{uuid4().hex}@x.test", hashed_password="x")
    db.add(founder)
    await db.flush()
    acme = Organization(
        id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex[:8]}", created_by_user_id=founder.id
    )
    db.add(acme)
    await db.flush()
    assert await kind_repo.pause(db, "ingest-document", acme.id, reason="five deaths in a row")
    service = BackgroundJobService(db)

    (listed,) = [
        kind for kind in (await service.overview()).kinds if kind.organization_id == acme.id
    ]
    assert (listed.kind, listed.organization_name) == ("ingest-document", "Acme")

    resumed = await service.resume_kind(
        "ingest-document", organization_id=acme.id, actor_user_id=ADMIN
    )
    assert (resumed.paused_at, resumed.organization_name) == (None, "Acme")
    (audit,) = (await db.execute(select(AppAdminAuditLog))).scalars().all()
    assert (audit.action, audit.target_id, audit.details) == (
        "background_kind.resumed",
        "ingest-document",
        {"organization_id": str(acme.id)},
    )


async def test_resuming_a_kind_that_is_not_paused_is_refused(db: AsyncSession) -> None:
    with pytest.raises(BadRequestError, match="not paused"):
        await BackgroundJobService(db).resume_kind(
            "expire-approvals", organization_id=None, actor_user_id=ADMIN
        )


async def test_an_unknown_kind_cannot_be_paused_or_resumed(db: AsyncSession) -> None:
    service = BackgroundJobService(db)
    with pytest.raises(NotFoundError):
        await service.pause_kind("no-such-kind", reason="x", actor_user_id=ADMIN)
    with pytest.raises(NotFoundError):
        await service.resume_kind("no-such-kind", organization_id=None, actor_user_id=ADMIN)


async def test_a_kind_that_never_died_reads_as_untouched(db: AsyncSession) -> None:
    await BackgroundJobService(db).pause_kind("reap-stale-runs", reason="x", actor_user_id=ADMIN)
    resumed = await BackgroundJobService(db).resume_kind(
        "reap-stale-runs", organization_id=None, actor_user_id=ADMIN
    )
    assert (resumed.consecutive_deaths, resumed.lease_lost) == (0, 0)
