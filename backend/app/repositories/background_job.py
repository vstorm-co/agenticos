"""Data access for the background job queue (#2219).

The statements here are the queue's guarantees, so each says which one it
keeps. The two that matter most:

* `claim` counts the attempt in the `UPDATE` that hands the job out. Nothing a
  job does afterwards - including killing the process that runs it - can take
  that attempt back, so a job that crashes its worker reaches `max_attempts`
  and stops rather than being handed out for ever.
* every write a worker makes about a job it holds carries the attempt count it
  claimed with (`fence`). A worker that lost its lease - stalled long enough
  for the rescuer to give the job to someone else - finds its write matches
  nothing, and the job's new holder is not overwritten.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    ColumnElement,
    String,
    case,
    cast,
    delete,
    exists,
    func,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.background_job import JOB_STATUSES, BackgroundJob, JobStatus

NOTIFY_CHANNEL = "background_jobs"
"""What a worker `LISTEN`s on; the payload is the pool that has new work."""

ERROR_LIMIT = 4000
"""Characters of an error kept on the row: enough for a traceback's last frames."""

ACTIVE_STATUSES = ("queued", "running")


@dataclass(frozen=True)
class ClaimedJob:
    """A job a worker now holds, with the attempt count that fences its writes."""

    id: UUID
    kind: str
    payload: dict[str, JsonValue]
    attempts: int
    max_attempts: int
    organization_id: UUID | None
    schedule_name: str | None


class FailOutcome(enum.StrEnum):
    """What a failed attempt led to."""

    RETRYING = "retrying"
    DEAD = "dead"
    SUPERSEDED = "superseded"
    """Not queued again: a newer copy under the same dedupe key already is."""
    LOST = "lost"
    """The worker no longer held the job: its write matched nothing."""


@dataclass(frozen=True)
class RescuedJob:
    """A running job whose lease ran out, as the rescuer left it."""

    id: UUID
    kind: str
    status: JobStatus
    organization_id: UUID | None

    @property
    def dead(self) -> bool:
        return self.status == "dead"


@dataclass(frozen=True)
class UnsettledEnd:
    """A dead or cancelled job whose settler has not run to the end yet."""

    id: UUID
    kind: str
    payload: dict[str, JsonValue]
    why: str


async def add(
    db: AsyncSession,
    *,
    kind: str,
    pool: str,
    payload: dict[str, JsonValue],
    max_attempts: int,
    priority: int,
    organization_id: UUID | None = None,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
    dedupe_active: bool = False,
    concurrency_key: str | None = None,
    schedule_name: str | None = None,
    idempotency_key: str | None = None,
) -> UUID | None:
    """Queue a job in the caller's transaction, and wake the pool's workers when it commits.

    Answers the new job's id, or `None` when the enqueue was dropped: a queued
    job already carries `dedupe_key`, or - with `dedupe_active` - a queued or
    *running* one does. Dropping is the contract, not an error. `NOTIFY` is
    transactional in Postgres: a rolled-back enqueue wakes nobody, and a
    committed one wakes the workers only once the row is there to claim.
    """
    if dedupe_key is not None and dedupe_active and await _active_with_key(db, dedupe_key):
        return None
    values: dict[str, object] = {
        "kind": kind,
        "pool": pool,
        "payload": payload,
        "max_attempts": max_attempts,
        "priority": priority,
        "organization_id": organization_id,
        "dedupe_key": dedupe_key,
        "concurrency_key": concurrency_key,
        "schedule_name": schedule_name,
        "idempotency_key": idempotency_key,
    }
    if run_after is not None:
        values["run_after"] = run_after
    statement = (
        insert(BackgroundJob)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            index_where=text("status = 'queued' AND dedupe_key IS NOT NULL"),
        )
        .returning(BackgroundJob.id)
    )
    job_id = (await db.execute(statement)).scalar_one_or_none()
    if job_id is not None:
        await _notify(db, pool)
    return job_id


# The subquery locks one claimable row and skips any another worker holds, and
# `FOR UPDATE` rechecks its own `WHERE` against the row's latest version once
# the lock is taken - so a job another claim moved on between the snapshot and
# the lock is not handed out twice. A kind paused for the whole deployment, or
# for the job's own organization, is not claimed; nor is
# a job whose `concurrency_key` is already running somewhere, and the partial
# unique index on running keys turns the one race left there - two claims of two
# such jobs at once - into a unique violation for the second, not a duplicate.
_CLAIM = text(
    """
    UPDATE background_jobs
    SET status = 'running',
        attempts = attempts + 1,
        lease_until = now() + make_interval(secs => :lease_seconds),
        worker_id = :worker_id,
        started_at = now(),
        updated_at = now()
    WHERE id = (
        SELECT j.id FROM background_jobs j
        WHERE j.status = 'queued'
          AND j.pool = :pool
          AND j.run_after <= now()
          AND NOT EXISTS (
              SELECT 1 FROM background_task_kinds k
              WHERE k.kind = j.kind AND k.paused_at IS NOT NULL
                AND (k.organization_id IS NULL OR k.organization_id = j.organization_id)
          )
          AND (
              j.concurrency_key IS NULL
              OR NOT EXISTS (
                  SELECT 1 FROM background_jobs r
                  WHERE r.status = 'running' AND r.concurrency_key = j.concurrency_key
              )
          )
        ORDER BY j.priority, j.run_after, j.id
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts, max_attempts, organization_id, schedule_name
    """
)


async def claim(
    db: AsyncSession, *, pool: str, worker_id: str, lease: timedelta
) -> ClaimedJob | None:
    """Hand the next job of `pool` to `worker_id`, counting the attempt. `None` when there is none."""
    row = (
        await db.execute(
            _CLAIM,
            {"pool": pool, "worker_id": worker_id, "lease_seconds": lease.total_seconds()},
        )
    ).one_or_none()
    if row is None:
        return None
    return ClaimedJob(
        id=row.id,
        kind=row.kind,
        payload=row.payload,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        organization_id=row.organization_id,
        schedule_name=row.schedule_name,
    )


async def extend_leases(
    db: AsyncSession, *, worker_id: str, job_ids: Sequence[UUID], lease: timedelta
) -> int:
    """Push out the lease of the jobs `worker_id` still owes an outcome for. Answers how many.

    The jobs the worker names, and only while they still name it: one the
    rescuer has given to someone else no longer does, and one whose settlement
    the worker abandoned is not named, so its lease runs out.
    """
    if not job_ids:
        return 0
    rows = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id.in_(job_ids),
            BackgroundJob.worker_id == worker_id,
            BackgroundJob.status == "running",
        )
        .values(lease_until=func.now() + lease)
        .returning(BackgroundJob.id)
    )
    return len(rows.all())


async def complete(
    db: AsyncSession, job_id: UUID, *, fence: int, result: dict[str, JsonValue] | None = None
) -> bool:
    """Record a job done, with what it answered. `False` when the worker no longer held it."""
    done = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == fence,
        )
        .values(
            status="succeeded",
            finished_at=func.now(),
            lease_until=None,
            last_error=None,
            result=result,
        )
        .returning(BackgroundJob.id)
    )
    return done.scalar_one_or_none() is not None


async def fail(
    db: AsyncSession, job_id: UUID, *, fence: int, error: str, retry_in: timedelta
) -> FailOutcome:
    """Record a failed attempt: queued again after `retry_in`, or dead at the last attempt."""
    row = (
        await db.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.status == "running",
                BackgroundJob.attempts == fence,
            )
            .values(
                status=_after_attempt(),
                run_after=func.now() + retry_in,
                finished_at=_finished_unless_queued(),
                lease_until=None,
                worker_id=None,
                last_error=error[:ERROR_LIMIT],
            )
            .returning(BackgroundJob.status)
        )
    ).scalar_one_or_none()
    if row is None:
        return FailOutcome.LOST
    return {"dead": FailOutcome.DEAD, "cancelled": FailOutcome.SUPERSEDED}.get(
        row, FailOutcome.RETRYING
    )


async def bury(db: AsyncSession, job_id: UUID, *, fence: int, error: str) -> bool:
    """End a job now, whatever attempts it has left: it can never succeed as queued.

    For a payload that no longer validates or a kind no worker knows - retrying
    either would only spend the attempts on the same refusal.
    """
    result = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == fence,
        )
        .values(
            status="dead",
            finished_at=func.now(),
            lease_until=None,
            worker_id=None,
            last_error=error[:ERROR_LIMIT],
        )
        .returning(BackgroundJob.id)
    )
    return result.scalar_one_or_none() is not None


async def unclaim(db: AsyncSession, job_id: UUID, *, fence: int) -> bool:
    """Put back a job claimed as its worker began to stop, before anything ran.

    Unlike `release`, the attempt is given back: nothing was started, so nothing
    the job does has happened. Fenced like every other write.
    """
    result = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == fence,
        )
        .values(
            status="queued",
            attempts=BackgroundJob.attempts - 1,
            lease_until=None,
            worker_id=None,
            started_at=None,
        )
        .returning(BackgroundJob.id)
    )
    return result.scalar_one_or_none() is not None


async def release(db: AsyncSession, job_id: UUID, *, fence: int) -> JobStatus | None:
    """Put back a job its worker stopped under: queued again if it has attempts left, else dead.

    The attempt stays spent. A job cancelled by a shutdown has run for as long as
    the drain allowed, and what it did - a model call paid for, a tool's side
    effect - happened; handing the attempt back would have let even a
    `max_attempts=1` agent run start again on the next worker. A job whose
    newer copy is already queued is withdrawn instead (`cancelled`). Answers the
    status it was left in; `None` when it was already taken over (fenced).
    """
    result = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == fence,
        )
        .values(
            status=_after_attempt(),
            finished_at=_finished_unless_queued(),
            last_error=(
                "the worker stopped while it ran (attempt "
                + cast(BackgroundJob.attempts, String)
                + " of "
                + cast(BackgroundJob.max_attempts, String)
                + ")"
            ),
            lease_until=None,
            worker_id=None,
        )
        .returning(BackgroundJob.status)
    )
    return result.scalar_one_or_none()


# Locked and skipped like the claim, so two rescuers sweeping at once never
# write the same death twice. The error says what is known and no more: the
# worker stopped renewing the lease, which is a crash, an OOM kill or a host
# that froze - the rescuer cannot tell which.
_RESCUE = text(
    """
    UPDATE background_jobs
    SET status = CASE WHEN attempts >= max_attempts THEN 'dead'
                      WHEN EXISTS (
                          SELECT 1 FROM background_jobs newer
                          WHERE newer.dedupe_key = background_jobs.dedupe_key
                            AND newer.status = 'queued' AND newer.id <> background_jobs.id
                      ) THEN 'cancelled'
                      ELSE 'queued' END,
        finished_at = CASE WHEN attempts >= max_attempts THEN now()
                           WHEN EXISTS (
                               SELECT 1 FROM background_jobs newer
                               WHERE newer.dedupe_key = background_jobs.dedupe_key
                                 AND newer.status = 'queued' AND newer.id <> background_jobs.id
                           ) THEN now()
                           ELSE NULL END,
        run_after = now() + make_interval(secs => :retry_seconds),
        last_error = 'worker lost: no heartbeat from ' || coalesce(worker_id, 'unknown worker')
            || ' since the lease ran out at ' || to_char(lease_until, 'YYYY-MM-DD HH24:MI:SS TZ')
            || ' (attempt ' || attempts || ' of ' || max_attempts || ')',
        lease_until = NULL,
        worker_id = NULL,
        updated_at = now()
    WHERE id IN (
        SELECT id FROM background_jobs
        WHERE status = 'running' AND lease_until < now()
        ORDER BY lease_until
        FOR UPDATE SKIP LOCKED
        LIMIT :limit
    )
    RETURNING id, kind, status, organization_id
    """
)


async def rescue_expired(
    db: AsyncSession, *, retry_in: timedelta, limit: int = 100
) -> list[RescuedJob]:
    """Take back every running job whose lease ran out, and say what became of each."""
    rows = (
        await db.execute(_RESCUE, {"retry_seconds": retry_in.total_seconds(), "limit": limit})
    ).all()
    return [
        RescuedJob(id=row.id, kind=row.kind, status=row.status, organization_id=row.organization_id)
        for row in rows
    ]


async def unsettled_ends(
    db: AsyncSession, *, within: timedelta = timedelta(days=1), limit: int = 50
) -> list[UnsettledEnd]:
    """The dead and cancelled jobs of the last `within` whose settlement is still owed.

    Newest first, and only that far back: a settler that fails every time - a bug
    rather than an outage - is retried for a day and then left, instead of every
    pass for good, and it never stands in front of an end that happened since.
    `why` is what the job ended on, or its status where nothing was written - a
    queued job an owner cancelled.
    """
    rows = await db.execute(
        select(
            BackgroundJob.id,
            BackgroundJob.kind,
            BackgroundJob.payload,
            func.coalesce(BackgroundJob.last_error, BackgroundJob.status),
        )
        .where(
            BackgroundJob.status.in_(("dead", "cancelled")),
            BackgroundJob.settled_at.is_(None),
            BackgroundJob.finished_at > func.now() - within,
        )
        .order_by(BackgroundJob.finished_at.desc())
        .limit(limit)
    )
    return [
        UnsettledEnd(id=job_id, kind=kind, payload=payload, why=why)
        for job_id, kind, payload, why in rows.tuples().all()
    ]


async def claim_settlement(db: AsyncSession, *, job_id: UUID) -> bool:
    """Lock `job_id` for its settler, if its settlement is still owed and nobody holds it.

    Two callers reach one end: the worker that saw it die settles it right after
    the death is committed, and every rescuer pass settles whatever it reads as
    owed - which includes an end whose settler is running at that moment (#2334).
    The row lock is held for the transaction, so the settler runs inside it: a
    second caller skips the locked row, and one arriving after the commit finds
    `settled_at` set. A settler that fails rolls the transaction back and leaves
    the end owed, for the next rescuer pass.
    """
    result = await db.execute(
        select(BackgroundJob.id)
        .where(BackgroundJob.id == job_id, BackgroundJob.settled_at.is_(None))
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none() is not None


async def mark_settled(db: AsyncSession, job_id: UUID) -> None:
    """Record that what `job_id` left outside the queue is closed."""
    await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job_id, BackgroundJob.settled_at.is_(None))
        .values(settled_at=func.now())
    )


async def _active_with_key(db: AsyncSession, dedupe_key: str) -> bool:
    """Whether a queued or running job holds `dedupe_key`, decided one enqueuer at a time.

    The unique index covers queued rows only, so the check and the insert after it
    would otherwise race: a second enqueuer reads before the first commits, a
    worker moves the first's row to `running`, and the second's insert meets no
    queued row to conflict with - two copies of one sync. The transaction-scoped
    advisory lock makes the next enqueuer of the key wait for this transaction,
    and its read, in a statement of its own, then sees what this one committed.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": dedupe_key}
    )
    result = await db.execute(
        select(BackgroundJob.id)
        .where(BackgroundJob.dedupe_key == dedupe_key, BackgroundJob.status.in_(ACTIVE_STATUSES))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def has_active_for_schedule(db: AsyncSession, schedule_name: str) -> bool:
    """Whether a job a schedule fired is still queued or running."""
    result = await db.execute(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.schedule_name == schedule_name,
            BackgroundJob.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get(db: AsyncSession, job_id: UUID) -> BackgroundJob | None:
    return await db.get(BackgroundJob, job_id)


async def latest_with_dedupe_key(db: AsyncSession, dedupe_key: str) -> BackgroundJob | None:
    """The most recently queued job under `dedupe_key`, whatever it has got to since."""
    result = await db.execute(
        select(BackgroundJob)
        .where(BackgroundJob.dedupe_key == dedupe_key)
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def replace_queued_payload(
    db: AsyncSession, job_id: UUID, payload: dict[str, JsonValue]
) -> bool:
    """Rewrite a job's payload while nobody has claimed it. `False` once a worker has."""
    result = await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
        .values(payload=payload)
        .returning(BackgroundJob.id)
    )
    return result.scalar_one_or_none() is not None


async def get_by_idempotency_key(
    db: AsyncSession, *, organization_id: UUID, idempotency_key: str
) -> BackgroundJob | None:
    """The job an organization already queued under this key, if any."""
    result = await db.execute(
        select(BackgroundJob).where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def list_page(
    db: AsyncSession,
    *,
    status: str | None,
    kind: str | None,
    pool: str | None,
    organization_id: UUID | None,
    before: tuple[datetime, UUID] | None,
    limit: int,
) -> Sequence[BackgroundJob]:
    """Jobs newest first, filtered, a keyset page at a time.

    `before` is the last row's `(created_at, id)`. Both, because one transaction
    queues many jobs under the same `created_at` - `now()` is the transaction's
    clock - and a cursor on the time alone would skip the rest of them.
    """
    statement = select(BackgroundJob)
    if status is not None:
        statement = statement.where(BackgroundJob.status == status)
    if kind is not None:
        statement = statement.where(BackgroundJob.kind == kind)
    if pool is not None:
        statement = statement.where(BackgroundJob.pool == pool)
    if organization_id is not None:
        statement = statement.where(BackgroundJob.organization_id == organization_id)
    if before is not None:
        statement = statement.where(tuple_(BackgroundJob.created_at, BackgroundJob.id) < before)
    statement = statement.order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
    return (await db.execute(statement.limit(limit))).scalars().all()


async def count_by_status(db: AsyncSession) -> dict[JobStatus, int]:
    """How many jobs are in each status, every status present even at zero."""
    result = await db.execute(
        select(BackgroundJob.status, func.count()).group_by(BackgroundJob.status)
    )
    found = dict(result.tuples().all())
    return {status: found.get(status, 0) for status in JOB_STATUSES}


@dataclass(frozen=True)
class FinishedBucket:
    """How many jobs finished each way in one slice of time."""

    start: datetime
    succeeded: int
    dead: int
    cancelled: int


@dataclass(frozen=True)
class KindActivity:
    """One kind's finished jobs in a window, and how long they ran and waited."""

    kind: str
    pool: str
    finished: int
    dead: int
    run_p50_seconds: float | None
    run_p95_seconds: float | None
    wait_p95_seconds: float | None


async def finished_by_bucket(
    db: AsyncSession, *, since: datetime, bucket: timedelta
) -> list[FinishedBucket]:
    """Jobs finished since `since`, counted per `bucket` from it; slices with none are absent."""
    start = func.date_bin(bucket, BackgroundJob.finished_at, since).label("start")
    result = await db.execute(
        select(
            start,
            func.count().filter(BackgroundJob.status == "succeeded"),
            func.count().filter(BackgroundJob.status == "dead"),
            func.count().filter(BackgroundJob.status == "cancelled"),
        )
        .where(BackgroundJob.finished_at >= since)
        .group_by(start)
        .order_by(start)
    )
    return [
        FinishedBucket(start=at, succeeded=succeeded, dead=dead, cancelled=cancelled)
        for at, succeeded, dead, cancelled in result.tuples().all()
    ]


async def activity_by_kind(db: AsyncSession, *, since: datetime) -> list[KindActivity]:
    """Each kind that finished a job since `since`, busiest first.

    Run time is `started_at` to `finished_at`, and wait is `run_after` to
    `started_at` - how long a due job sat before a worker took it, which is the
    figure that says the pool is short of workers. A cancelled job that never
    started has neither, and the percentiles leave it out.
    """
    run = func.extract("epoch", BackgroundJob.finished_at - BackgroundJob.started_at)
    wait = func.extract("epoch", BackgroundJob.started_at - BackgroundJob.run_after)
    finished = func.count().label("finished")
    result = await db.execute(
        select(
            BackgroundJob.kind,
            func.min(BackgroundJob.pool),
            finished,
            func.count().filter(BackgroundJob.status == "dead"),
            func.percentile_cont(0.5).within_group(run),
            func.percentile_cont(0.95).within_group(run),
            func.percentile_cont(0.95).within_group(wait),
        )
        .where(BackgroundJob.finished_at >= since)
        .group_by(BackgroundJob.kind)
        .order_by(finished.desc(), BackgroundJob.kind)
    )
    return [
        KindActivity(
            kind=kind,
            pool=pool,
            finished=count,
            dead=dead,
            run_p50_seconds=p50,
            run_p95_seconds=p95,
            wait_p95_seconds=waited,
        )
        for kind, pool, count, dead, p50, p95, waited in result.tuples().all()
    ]


async def oldest_due_since(db: AsyncSession, *, now: datetime) -> datetime | None:
    """When the longest-waiting due job became due, or `None` when nothing is waiting."""
    result = await db.execute(
        select(func.min(BackgroundJob.run_after)).where(
            BackgroundJob.status == "queued", BackgroundJob.run_after <= now
        )
    )
    return result.scalar_one()


async def queued_with_key(db: AsyncSession, dedupe_key: str) -> bool:
    """Whether a queued job holds `dedupe_key` - which a requeued copy would collide with."""
    result = await db.execute(
        select(BackgroundJob.id)
        .where(BackgroundJob.dedupe_key == dedupe_key, BackgroundJob.status == "queued")
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def requeue_dead(db: AsyncSession, job_id: UUID) -> bool:
    """Give a dead job a fresh set of attempts. `False` when it is not dead."""
    pool = (
        await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id, BackgroundJob.status == "dead")
            # Unsettled again: an end this retry reaches is a new one to settle.
            .values(
                status="queued", attempts=0, run_after=func.now(), finished_at=None, settled_at=None
            )
            .returning(BackgroundJob.pool)
        )
    ).scalar_one_or_none()
    if pool is None:
        return False
    await _notify(db, pool)
    return True


async def cancel_queued(db: AsyncSession, job_id: UUID) -> bool:
    """Withdraw a job nobody has started. `False` when it is not queued."""
    result = await db.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job_id, BackgroundJob.status == "queued")
        .values(status="cancelled", finished_at=func.now())
        .returning(BackgroundJob.id)
    )
    return result.scalar_one_or_none() is not None


async def delete_finished_before(db: AsyncSession, *, cutoff: datetime, limit: int) -> int:
    """Forget finished jobs older than `cutoff`, at most `limit` per call. Answers how many."""
    doomed = (
        select(BackgroundJob.id)
        .where(
            BackgroundJob.status.in_(("succeeded", "dead", "cancelled")),
            BackgroundJob.finished_at < cutoff,
        )
        .limit(limit)
        .scalar_subquery()
    )
    rows = await db.execute(
        delete(BackgroundJob).where(BackgroundJob.id.in_(doomed)).returning(BackgroundJob.id)
    )
    return len(rows.all())


async def _notify(db: AsyncSession, pool: str) -> None:
    await db.execute(
        text("SELECT pg_notify(:channel, :pool)"), {"channel": NOTIFY_CHANNEL, "pool": pool}
    )


def _superseded() -> ColumnElement[bool]:
    """A newer copy of this job is queued under its dedupe key.

    The unique index allows one queued row per key, so putting this one back
    would be a unique violation - which wedged the settle, then the rescue, and
    with the running row holding the concurrency key, the source's whole queue
    (Codex, #2248). The newer copy does the same work, so this one is withdrawn.
    """
    newer = aliased(BackgroundJob)
    return (
        exists()
        .where(
            newer.dedupe_key == BackgroundJob.dedupe_key,
            newer.status == "queued",
            newer.id != BackgroundJob.id,
        )
        .correlate(BackgroundJob)
    )


def _after_attempt() -> ColumnElement[str]:
    """`dead` once the attempt just made was the last, `cancelled` when a newer copy
    is queued, `queued` otherwise."""
    return case(
        (BackgroundJob.attempts >= BackgroundJob.max_attempts, "dead"),
        (_superseded(), "cancelled"),
        else_="queued",
    )


def _finished_unless_queued() -> ColumnElement[datetime | None]:
    return case(
        (BackgroundJob.attempts >= BackgroundJob.max_attempts, func.now()),
        (_superseded(), func.now()),
        else_=None,
    )


async def lock_workspace_attempt(
    db: AsyncSession, job_id: UUID, *, attempt: int
) -> BackgroundJob | None:
    """Fence activation against cancellation, takeover and an expired lease."""
    result = await db.execute(
        select(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == attempt,
            BackgroundJob.lease_until > datetime.now(UTC),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def workspace_move_progress(
    db: AsyncSession, job_id: UUID, *, attempt: int, result: dict[str, JsonValue]
) -> bool:
    changed = await db.execute(
        update(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.status == "running",
            BackgroundJob.attempts == attempt,
            BackgroundJob.lease_until > datetime.now(UTC),
        )
        .values(result=result)
        .returning(BackgroundJob.id)
    )
    return changed.scalar_one_or_none() is not None


async def for_project_moves(db: AsyncSession, ids: list[UUID]) -> dict[UUID, BackgroundJob]:
    if not ids:
        return {}
    rows = await db.execute(select(BackgroundJob).where(BackgroundJob.id.in_(ids)))
    return {row.id: row for row in rows.scalars().all()}
