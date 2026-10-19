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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, NotFoundError
from app.repositories import background_job as background_job_repo
from app.repositories import background_schedule as background_schedule_repo
from app.repositories import background_task_kind as background_task_kind_repo
from app.repositories import background_worker as background_worker_repo
from app.schemas.background_job import (
    BackgroundJobList,
    BackgroundJobRead,
    BackgroundJobsOverview,
    BackgroundKindRead,
    BackgroundScheduleRead,
    BackgroundWorkerRead,
    JobPool,
    JobStatus,
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


async def tell_owners_paused(db: AsyncSession, kind: str, reason: str) -> None:
    """Tell the deployment's owners a kind of job is paused, in the pausing transaction.

    The worker's circuit breaker calls this once per pause; the notification is
    written with the pause, so it is never sent for a pause that rolled back.
    """
    from app.services.notifications import NotificationService

    await NotificationService(db).background_task_paused(
        kind, reason=reason, paused_at=datetime.now(UTC)
    )


_PAGE_LIMIT = 200
_WORKER_SILENT_AFTER = timedelta(minutes=2)


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
                BackgroundKindRead.model_validate(kind)
                for kind in await background_task_kind_repo.list_all(self.db)
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
        """Give a dead job a fresh set of attempts, and audit who did."""
        if not await background_job_repo.requeue_dead(self.db, job_id):
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
        """Withdraw a job nobody has started, and audit who did."""
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
        """Stop workers claiming a kind until it is resumed. Pausing a paused kind changes nothing."""
        self._known(kind)
        if await background_task_kind_repo.pause(self.db, kind, reason=reason):
            await record_audit(
                self.db,
                actor_user_id=actor_user_id,
                action="background_kind.paused",
                target_type="background_kind",
                target_id=kind,
                details={"reason": reason},
            )
        return await self._kind(kind)

    async def resume_kind(self, kind: str, *, actor_user_id: UUID) -> BackgroundKindRead:
        """Let workers claim a kind again, starting its run of deaths afresh."""
        self._known(kind)
        if not await background_task_kind_repo.resume(self.db, kind):
            raise BadRequestError(message="This kind of job is not paused.", details={"kind": kind})
        await record_audit(
            self.db,
            actor_user_id=actor_user_id,
            action="background_kind.resumed",
            target_type="background_kind",
            target_id=kind,
        )
        return await self._kind(kind)

    async def _read(self, job_id: UUID) -> BackgroundJobRead:
        job = await background_job_repo.get(self.db, job_id)
        if job is None:
            raise NotFoundError(
                message="Background job not found.", details={"job_id": str(job_id)}
            )
        await self.db.refresh(job)
        return BackgroundJobRead.model_validate(job)

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

    async def _kind(self, kind: str) -> BackgroundKindRead:
        for row in await background_task_kind_repo.list_all(self.db):
            if row.kind == kind:
                return BackgroundKindRead.model_validate(row)
        return BackgroundKindRead(
            kind=kind, consecutive_deaths=0, lease_lost=0, paused_at=None, paused_reason=None
        )

    @staticmethod
    def _known(kind: str) -> None:
        if kind not in TASKS:
            raise NotFoundError(message="No such kind of background job.", details={"kind": kind})
