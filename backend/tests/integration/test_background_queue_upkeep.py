"""The queue's upkeep and the corners of its bookkeeping (#2219).

The retention sweep forgets finished history and nothing else; a pause is
announced to the deployment's owners in the pausing transaction; the panel's
refusals and filters say what they mean; and a schedule row the code no longer
declares fires nothing while it waits to be forgotten.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.background_job import BackgroundJob
from app.db.models.notification import Notification
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import background_job as job_repo
from app.repositories import background_schedule as schedule_repo
from app.services.background_jobs import BackgroundJobService, tell_owners_paused
from app.worker import schedules
from app.worker.tasks import background_tasks

pytestmark = pytest.mark.anyio

NOW = datetime.now(UTC)


async def _job(
    db: AsyncSession,
    *,
    kind: str = "expire-approvals",
    pool: str = "system",
    organization_id: UUID | None = None,
    run_after: datetime | None = None,
) -> BackgroundJob:
    job_id = await job_repo.add(
        db,
        kind=kind,
        pool=pool,
        payload={},
        max_attempts=1,
        priority=1,
        organization_id=organization_id,
        run_after=run_after,
    )
    assert job_id is not None
    job = await db.get(BackgroundJob, job_id)
    assert job is not None
    return job


async def test_the_sweep_forgets_old_finished_jobs_in_batches_and_keeps_the_rest(
    db: AsyncSession,
) -> None:
    old = NOW - timedelta(days=30)
    doomed = [await _job(db) for _ in range(5)]
    recent = await _job(db)
    waiting = await _job(db)
    await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id.in_([job.id for job in doomed]))
        .values(status="succeeded", finished_at=old, created_at=old)
    )
    await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == recent.id)
        .values(status="dead", finished_at=NOW)
    )
    await db.execute(
        update(BackgroundJob).where(BackgroundJob.id == waiting.id).values(created_at=old)
    )

    @asynccontextmanager
    async def this_session():
        yield db

    with (
        patch.object(background_tasks, "get_db_context", this_session),
        patch.object(background_tasks, "_BATCH", 2),
    ):
        assert await background_tasks.sweep_background_jobs() == 5
        assert await background_tasks.sweep_background_jobs() == 0

    left = set((await db.execute(select(BackgroundJob.id))).scalars())
    assert left == {recent.id, waiting.id}


async def test_a_pause_is_announced_to_every_active_owner_and_nobody_else(
    db: AsyncSession,
) -> None:
    owner = User(id=uuid4(), email=f"{uuid4().hex}@x.test", hashed_password="x", is_app_admin=True)
    retired = User(
        id=uuid4(),
        email=f"{uuid4().hex}@x.test",
        hashed_password="x",
        is_app_admin=True,
        is_active=False,
    )
    member = User(id=uuid4(), email=f"{uuid4().hex}@x.test", hashed_password="x")
    db.add_all([owner, retired, member])
    await db.flush()

    await tell_owners_paused(db, "ingest-document", None, "5 deaths in a row")

    sent = (await db.execute(select(Notification))).scalars().all()
    assert [(row.recipient_user_id, row.event_type) for row in sent] == [
        (owner.id, "background_task_paused")
    ]
    assert "ingest-document" in sent[0].summary


async def test_a_pause_for_one_organization_names_it(db: AsyncSession) -> None:
    """The others still run, so the owner is told whose jobs stopped (#2248)."""
    owner = User(id=uuid4(), email=f"{uuid4().hex}@x.test", hashed_password="x", is_app_admin=True)
    db.add(owner)
    await db.flush()
    acme = Organization(
        id=uuid4(), name="Acme", slug=f"acme-{uuid4().hex[:8]}", created_by_user_id=owner.id
    )
    db.add(acme)
    await db.flush()

    await tell_owners_paused(db, "ingest-document", acme.id, "5 deaths in a row")

    (sent,) = (await db.execute(select(Notification))).scalars().all()
    assert "ingest-document are paused for Acme: 5 deaths in a row" in sent.summary


async def test_with_no_owner_a_pause_is_announced_to_nobody(db: AsyncSession) -> None:
    await tell_owners_paused(db, "ingest-document", None, "5 deaths in a row")

    assert (await db.execute(select(Notification))).scalars().all() == []


async def test_the_panel_says_missing_for_a_job_that_is_not_there(db: AsyncSession) -> None:
    service = BackgroundJobService(db)
    for action in (service.retry, service.cancel):
        with pytest.raises(NotFoundError):
            await action(uuid4(), actor_user_id=uuid4())


async def test_the_list_narrows_by_kind_pool_and_organization(db: AsyncSession) -> None:
    organization = uuid4()
    wanted = await _job(db, kind="ingest-document", pool="ingest", organization_id=organization)
    await _job(db, kind="ingest-document", pool="ingest")
    await _job(db, kind="sync-source", pool="ingest", organization_id=organization)

    page = await BackgroundJobService(db).list_jobs(
        status=None,
        kind="ingest-document",
        pool="ingest",
        organization_id=organization,
        before=None,
        limit=10,
    )

    assert [job.id for job in page.items] == [wanted.id]


async def test_a_job_queued_for_later_is_not_claimed_before_then(db: AsyncSession) -> None:
    await _job(db, run_after=NOW + timedelta(hours=1))

    assert (
        await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1)) is None
    )


async def test_a_schedule_row_the_code_no_longer_declares_fires_nothing(db: AsyncSession) -> None:
    await schedule_repo.declare(
        db,
        name="retired-sweep",
        kind="retired-sweep",
        interval_seconds=60,
        overlap="skip",
        misfire="latest",
        grace_seconds=60,
        now=NOW - timedelta(minutes=5),
        first_run_at=NOW - timedelta(minutes=5),
    )

    assert await schedules.fire_due(db, [], now=NOW) == []
    assert (await db.execute(select(BackgroundJob))).scalars().all() == []


async def test_a_job_that_can_never_succeed_is_buried_by_its_holder_only(db: AsyncSession) -> None:
    job = await _job(db)
    claimed = await job_repo.claim(db, pool="system", worker_id="w", lease=timedelta(minutes=1))
    assert claimed is not None

    assert await job_repo.bury(db, job.id, fence=claimed.attempts + 1, error="stale") is False
    assert await job_repo.bury(db, job.id, fence=claimed.attempts, error="no such kind") is True

    await db.refresh(job)
    assert (job.status, job.last_error) == ("dead", "no such kind")
