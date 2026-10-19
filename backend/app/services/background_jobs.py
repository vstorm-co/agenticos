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

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import background_job as background_job_repo
from app.worker.jobs import Payload, Priority, Task


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
    )
