"""Queueing background work, and what the deployment's owner can do about it (#2219).

`enqueue` is how a service asks for work to happen later. It writes the job in
the caller's own transaction - the session the change is being made on - so
the change and the work it asks for commit together, or roll back together:

    await enqueue(self.db, INGEST_DOCUMENT, IngestDocument(...), organization_id=org.id)

That replaces `spawn_after_commit` for anything that must survive a restart,
and closes the gap it left: an in-process task died with the process that
queued it, and a Prefect submission made after the commit was lost if the
process died between the two (#1349).
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.db.models.background_task_kind import BackgroundTaskKind
from app.repositories import background_job as background_job_repo
from app.repositories import background_schedule as background_schedule_repo
from app.repositories import background_task_kind as background_task_kind_repo
from app.repositories import background_worker as background_worker_repo
from app.schemas.background_job import (
    ActivityWindow,
    BackgroundJobList,
    BackgroundJobRead,
    BackgroundJobsActivity,
    BackgroundJobsOverview,
    BackgroundKindRead,
    BackgroundScheduleRead,
    BackgroundWorkerRead,
    FinishedBucketRead,
    JobPool,
    JobStatus,
    KindActivityRead,
)
from app.worker.jobs import TASKS, Payload, Priority, Task


async def enqueue[P: Payload](
    db: AsyncSession,
    task: Task[P],
    payload: P,
    *,
    organization_id: UUID | None = None,
    run_after: datetime | None = None,
    priority: Priority | None = None,
    dedupe_key: str | None = None,
    dedupe_active: bool = False,
    concurrency_key: str | None = None,
    schedule_name: str | None = None,
    idempotency_key: str | None = None,
) -> UUID | None:
    """Queue `task` with `payload` in `db`'s transaction. `None` when a dedupe key dropped it.

    `dedupe_key` keeps at most one queued copy; with `dedupe_active` a queued
    or running copy is enough to drop this one. `concurrency_key` lets copies
    queue but runs them one at a time. `organization_id` is for the panel's
    filters and nothing else: the job carries whatever scope its work needs in
    its payload, and re-establishes it when it runs.
    """
    return await background_job_repo.add(
        db,
        kind=task.kind,
        pool=task.pool.value,
        payload=task.dump(payload),
        max_attempts=task.max_attempts,
        priority=int(task.priority if priority is None else priority),
        organization_id=organization_id,
        run_after=run_after,
        dedupe_key=dedupe_key,
        dedupe_active=dedupe_active,
        concurrency_key=concurrency_key,
        schedule_name=schedule_name,
        idempotency_key=idempotency_key,
    )


async def tell_owners_paused(
    db: AsyncSession, kind: str, organization_id: UUID | None, reason: str
) -> None:
    """Tell the deployment's owners a kind of job is paused, in the pausing transaction.

    The worker's circuit breaker calls this once per pause; the notification is
    written with the pause, so it is never sent for a pause that rolled back.
    """
    from app.repositories import organization_repo
    from app.services.notifications import NotificationService

    organization = (
        None if organization_id is None else await organization_repo.get_by_id(db, organization_id)
    )
    await NotificationService(db).background_task_paused(
        kind,
        organization_name=None if organization is None else organization.name,
        reason=reason,
        paused_at=datetime.now(UTC),
    )


_PAGE_LIMIT = 200
_WORKER_SILENT_AFTER = timedelta(minutes=2)
# A window and the slice it is charted in: 24 hours, or 28 six-hour slices.
_WINDOWS: dict[ActivityWindow, tuple[timedelta, int]] = {
    "day": (timedelta(hours=1), 24),
    "week": (timedelta(hours=6), 28),
}


class BackgroundJobService:
    """What the deployment's owner can see and do on the Background jobs page.

    Deployment-wide by design: the route behind it is `CurrentAppAdmin` alone
    (decided for #2219 - no per-organization view, no member view), so nothing
    here narrows by organization except the filter the owner chooses.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(self) -> BackgroundJobsOverview:
        since = datetime.now(UTC) - _WORKER_SILENT_AFTER
        return BackgroundJobsOverview(
            counts=await background_job_repo.count_by_status(self.db),
            kinds=[
                _kind_read(kind, name)
                for kind, name in await background_task_kind_repo.list_all(self.db)
            ],
            workers=[
                BackgroundWorkerRead.model_validate(worker)
                for worker in await background_worker_repo.list_seen_since(self.db, since=since)
            ],
            schedules=[
                BackgroundScheduleRead.model_validate(schedule)
                for schedule in await background_schedule_repo.list_all(self.db)
            ],
        )

    async def activity(self, window: ActivityWindow) -> BackgroundJobsActivity:
        """What finished in the last day or week, sliced, by kind, and what waits now."""
        bucket, slices = _WINDOWS[window]
        now = datetime.now(UTC)
        # Slices start on the hour, so the chart's columns do not shift with every
        # read; the last one is the slice now is in.
        epoch = datetime(2000, 1, 1, tzinfo=UTC)
        current = epoch + (now - epoch) // bucket * bucket
        since = current - (slices - 1) * bucket
        found = {
            row.start: row
            for row in await background_job_repo.finished_by_bucket(
                self.db, since=since, bucket=bucket
            )
        }
        buckets = []
        for index in range(slices):
            start = since + index * bucket
            row = found.get(start)
            buckets.append(
                FinishedBucketRead(
                    start=start,
                    succeeded=row.succeeded if row else 0,
                    dead=row.dead if row else 0,
                    cancelled=row.cancelled if row else 0,
                )
            )
        oldest = await background_job_repo.oldest_due_since(self.db, now=now)
        return BackgroundJobsActivity(
            window=window,
            bucket_seconds=int(bucket.total_seconds()),
            buckets=buckets,
            kinds=[
                KindActivityRead.model_validate(row, from_attributes=True)
                for row in await background_job_repo.activity_by_kind(self.db, since=since)
            ],
            oldest_wait_seconds=None if oldest is None else (now - oldest).total_seconds(),
        )

    async def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        kind: str | None = None,
        pool: JobPool | None = None,
        organization_id: UUID | None = None,
        before: tuple[datetime, UUID] | None = None,
        limit: int = 50,
    ) -> BackgroundJobList:
        """Newest first, a keyset page at a time: `before` is the previous page's cursor."""
        limit = max(1, min(limit, _PAGE_LIMIT))
        rows = await background_job_repo.list_page(
            self.db,
            status=status,
            kind=kind,
            pool=pool,
            organization_id=organization_id,
            before=before,
            limit=limit + 1,
        )
        items = [BackgroundJobRead.model_validate(row) for row in rows[:limit]]
        if len(rows) <= limit:
            return BackgroundJobList(items=items)
        return BackgroundJobList(
            items=items, next_before=items[-1].created_at, next_before_id=items[-1].id
        )

    async def retry(self, job_id: UUID, *, actor_user_id: UUID) -> BackgroundJobRead:
        """Give a dead job a fresh set of attempts, and audit who did.

        Raises:
            NotFoundError: No such job.
            BadRequestError: The job is not dead.
            AlreadyExistsError: A newer job for the same work is already queued,
                and two queued copies of one dedupe key cannot exist.
        """
        job = await background_job_repo.get(self.db, job_id)
        if (
            job is not None
            and job.dedupe_key is not None
            and await background_job_repo.queued_with_key(self.db, job.dedupe_key)
        ):
            raise self._superseded(job_id)
        try:
            async with self.db.begin_nested():
                requeued = await background_job_repo.requeue_dead(self.db, job_id)
        except IntegrityError:
            # The newer copy was queued between the check above and this update.
            raise self._superseded(job_id) from None
        if not requeued:
            raise await self._refusal(job_id, action="retried", allowed="dead")
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="background_job.retried",
            target_type="background_job",
            target_id=str(job_id),
        )
        return await self._read(job_id)

    async def cancel(self, job_id: UUID, *, actor_user_id: UUID) -> BackgroundJobRead:
        """Withdraw a job nobody has started, and audit who did.

        Raises:
            NotFoundError: No such job.
            BadRequestError: The job is not queued, or is of a kind whose document
                or sync log would be left in progress for good.
        """
        job = await background_job_repo.get(self.db, job_id)
        task = None if job is None else TASKS.get(job.kind)
        if task is not None and not task.cancellable:
            raise BadRequestError(
                message=(
                    f"A {task.kind} job cannot be cancelled: its document or sync would stay "
                    "in progress with nothing left to finish it. Pause the kind instead."
                ),
                details={"job_id": str(job_id), "kind": task.kind},
            )
        if not await background_job_repo.cancel_queued(self.db, job_id):
            raise await self._refusal(job_id, action="cancelled", allowed="queued")
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="background_job.cancelled",
            target_type="background_job",
            target_id=str(job_id),
        )
        return await self._read(job_id)

    async def pause_kind(
        self, kind: str, *, reason: str, actor_user_id: UUID
    ) -> BackgroundKindRead:
        """Stop workers claiming a kind until it is resumed, in every organization.

        Pausing a paused kind changes nothing.
        """
        self._known(kind)
        if await background_task_kind_repo.pause(self.db, kind, None, reason=reason):
            await record_audit(
                self.db,
                actor_user_id=actor_user_id,
                action="background_kind.paused",
                target_type="background_kind",
                target_id=kind,
                details={"reason": reason},
            )
        return await self._kind(kind, None)

    async def resume_kind(
        self, kind: str, *, organization_id: UUID | None, actor_user_id: UUID
    ) -> BackgroundKindRead:
        """Let workers claim a kind again, in one organization or everywhere, its deaths counted afresh."""
        self._known(kind)
        if not await background_task_kind_repo.resume(self.db, kind, organization_id):
            raise BadRequestError(
                message="This kind of job is not paused here.",
                details={
                    "kind": kind,
                    "organization_id": None if organization_id is None else str(organization_id),
                },
            )
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="background_kind.resumed",
            target_type="background_kind",
            target_id=kind,
            details=None if organization_id is None else {"organization_id": str(organization_id)},
        )
        return await self._kind(kind, organization_id)

    async def _read(self, job_id: UUID) -> BackgroundJobRead:
        job = await background_job_repo.get(self.db, job_id)
        assert job is not None, "read back in the transaction that just updated it"
        await self.db.refresh(job)
        return BackgroundJobRead.model_validate(job)

    @staticmethod
    def _superseded(job_id: UUID) -> AlreadyExistsError:
        return AlreadyExistsError(
            message="A newer job for the same work is already queued; this one cannot be retried.",
            details={"job_id": str(job_id)},
        )

    async def _refusal(self, job_id: UUID, *, action: str, allowed: str) -> Exception:
        job = await background_job_repo.get(self.db, job_id)
        if job is None:
            return NotFoundError(
                message="Background job not found.", details={"job_id": str(job_id)}
            )
        return BadRequestError(
            message=f"Only a {allowed} job can be {action}; this one is {job.status}.",
            details={"job_id": str(job_id), "status": job.status},
        )

    async def _kind(self, kind: str, organization_id: UUID | None) -> BackgroundKindRead:
        found = await background_task_kind_repo.get(self.db, kind, organization_id)
        assert found is not None, "pausing writes the row, and only a paused kind is resumed"
        row, name = found
        # The pause and the resume are statements, not ORM writes: refresh so
        # the row read back is the one they left.
        await self.db.refresh(row)
        return _kind_read(row, name)

    @staticmethod
    def _known(kind: str) -> None:
        if kind not in TASKS:
            raise NotFoundError(message="No such kind of background job.", details={"kind": kind})


def _kind_read(row: BackgroundTaskKind, organization_name: str | None) -> BackgroundKindRead:
    return BackgroundKindRead.model_validate(row).model_copy(
        update={"organization_name": organization_name}
    )
