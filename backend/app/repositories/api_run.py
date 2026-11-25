"""Queue lookups for steering active API runs without consuming their fallback jobs."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_job import BackgroundJob
from app.db.models.background_task_kind import BackgroundTaskKind
from app.repositories.background_job import attempt_token

if TYPE_CHECKING:
    from app.worker.jobs import RunAgent


def _api_run_identity(job: RunAgent) -> ColumnElement[bool]:
    """An issuer's other key (or session) must not drive this credential's tools."""
    return (
        (BackgroundJob.kind == "run-agent")
        & (BackgroundJob.organization_id == job.organization_id)
        & (BackgroundJob.concurrency_key == f"conversation:{job.conversation_id}")
        & BackgroundJob.payload.contains(
            job.model_dump(
                mode="json", include={"agent_id", "user_id", "api_key_id", "environment_id"}
            )
        )
    )


async def api_steering_target(
    db: AsyncSession, *, job: RunAgent, for_update: bool = False
) -> UUID | None:
    """Pin to this attempt, not whichever run happens to read its inbox next."""
    candidate = select(BackgroundJob.id, BackgroundJob.started_at, BackgroundJob.lease_until).where(
        _api_run_identity(job),
        BackgroundJob.status == "running",
    )
    if for_update:
        # Materialize the locked row before checking wall time: the lock
        # may have taken until after the lease expired.
        locked = candidate.with_for_update().cte().prefix_with("MATERIALIZED")
        statement = select(locked.c.id, locked.c.started_at).where(
            locked.c.lease_until > func.clock_timestamp()
        )
    else:
        statement = candidate.where(BackgroundJob.lease_until > func.clock_timestamp())
    row = (await db.execute(statement)).one_or_none()
    return None if row is None or row.started_at is None else attempt_token(row.id, row.started_at)


async def lock_api_steering_target(db: AsyncSession, *, job: RunAgent) -> bool:
    """Do not let settlement or rescue race this attempt's transfer of queued input."""
    target = await api_steering_target(db, job=job, for_update=True)
    return target is not None and target == job.execution_token


async def queued_api_steers(db: AsyncSession, *, job: RunAgent) -> list[BackgroundJob]:
    """Only pending additions for this exact attempt; all other jobs remain ordinary turns."""
    rows = await db.scalars(
        select(BackgroundJob)
        .where(
            _api_run_identity(job),
            BackgroundJob.status == "queued",
            BackgroundJob.payload["steer_target"].astext == str(job.execution_token),
            # Taking a correction starts queued work, just as a worker claim does.
            ~exists().where(
                BackgroundTaskKind.kind == BackgroundJob.kind,
                BackgroundTaskKind.paused_at.is_not(None),
                BackgroundTaskKind.organization_id.is_(None)
                | (BackgroundTaskKind.organization_id == job.organization_id),
            ),
        )
        .order_by(BackgroundJob.created_at, BackgroundJob.id)
        .limit(8)
        .with_for_update()
    )
    return list(rows)


def leave_api_steer_queued(row: BackgroundJob) -> None:
    """Stop offering a locked correction without changing its fallback job or receipt."""
    row.payload = {key: value for key, value in row.payload.items() if key != "steer_target"}
