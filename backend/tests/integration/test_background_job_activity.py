"""The Background jobs page's charts, against the real table (#2248).

The slices are `date_bin` and the timings `percentile_cont`, both Postgres's
answer rather than a mock's. Each test names its own kinds, so the per-kind
figures are exact; the slices count every kind, so they are held to at least
what a test wrote.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_job import BackgroundJob
from app.services.background_jobs import BackgroundJobService

pytestmark = pytest.mark.anyio


async def _finished(
    db: AsyncSession,
    kind: str,
    *,
    status: str = "succeeded",
    ago: timedelta,
    ran: timedelta = timedelta(seconds=10),
    waited: timedelta = timedelta(seconds=2),
) -> None:
    finished_at = datetime.now(UTC) - ago
    started_at = finished_at - ran
    db.add(
        BackgroundJob(
            id=uuid4(),
            kind=kind,
            pool="system",
            status=status,
            payload={},
            max_attempts=1,
            attempts=1,
            run_after=started_at - waited,
            started_at=started_at,
            finished_at=finished_at,
        )
    )
    await db.flush()


async def test_a_day_is_24_hourly_slices_ending_in_the_current_one(db) -> None:
    activity = await BackgroundJobService(db).activity("day")

    assert activity.bucket_seconds == 3600
    assert len(activity.buckets) == 24
    starts = [bucket.start for bucket in activity.buckets]
    assert starts == sorted(starts)
    assert all(start.minute == 0 and start.second == 0 for start in starts)
    assert starts[-1] <= datetime.now(UTC) < starts[-1] + timedelta(hours=1)


async def test_a_week_is_28_six_hour_slices(db) -> None:
    activity = await BackgroundJobService(db).activity("week")

    assert activity.bucket_seconds == 6 * 3600
    assert len(activity.buckets) == 28
    assert {bucket.start.hour for bucket in activity.buckets} <= {0, 6, 12, 18}


async def test_each_finish_lands_in_its_slice_counted_by_outcome(db) -> None:
    kind = f"chart-{uuid4().hex[:8]}"
    await _finished(db, kind, ago=timedelta(minutes=1))
    await _finished(db, kind, status="dead", ago=timedelta(minutes=1))
    await _finished(db, kind, status="cancelled", ago=timedelta(minutes=1))
    await _finished(db, kind, ago=timedelta(hours=30))

    activity = await BackgroundJobService(db).activity("day")
    # The slice the three finishes are in, not the last one: a minute ago is the
    # previous hour for a test that starts a few seconds past one, as a CI run at
    # 09:00:13 did.
    finished = datetime.now(UTC) - timedelta(minutes=1)
    width = timedelta(seconds=activity.bucket_seconds)
    current = next(b for b in activity.buckets if b.start <= finished < b.start + width)

    assert current.succeeded >= 1
    assert current.dead >= 1
    assert current.cancelled >= 1


async def test_a_kind_reports_how_long_its_jobs_ran_and_waited(db) -> None:
    kind = f"timed-{uuid4().hex[:8]}"
    for seconds in (10, 20, 30, 40):
        await _finished(
            db,
            kind,
            ago=timedelta(minutes=5),
            ran=timedelta(seconds=seconds),
            waited=timedelta(seconds=seconds / 10),
        )
    await _finished(
        db,
        kind,
        status="dead",
        ago=timedelta(minutes=5),
        ran=timedelta(seconds=50),
        waited=timedelta(seconds=5),
    )
    # Outside the day, so not counted.
    await _finished(db, kind, ago=timedelta(days=2), ran=timedelta(hours=1))

    activity = await BackgroundJobService(db).activity("day")

    row = next(row for row in activity.kinds if row.kind == kind)
    assert (row.pool, row.finished, row.dead) == ("system", 5, 1)
    assert row.run_p50_seconds == pytest.approx(30)
    assert row.run_p95_seconds == pytest.approx(48)
    assert row.wait_p95_seconds == pytest.approx(4.8)


async def test_the_wait_now_is_the_longest_due_job_and_ignores_one_not_yet_due(db) -> None:
    now = datetime.now(UTC)
    for run_after in (now - timedelta(minutes=7), now + timedelta(hours=1)):
        db.add(
            BackgroundJob(
                id=uuid4(),
                kind=f"waiting-{uuid4().hex[:8]}",
                pool="ingest",
                status="queued",
                payload={},
                max_attempts=1,
                run_after=run_after,
            )
        )
    await db.flush()

    activity = await BackgroundJobService(db).activity("day")

    assert activity.oldest_wait_seconds is not None
    assert activity.oldest_wait_seconds >= 7 * 60 - 5
