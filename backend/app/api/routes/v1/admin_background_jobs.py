"""The Background jobs page: the deployment's queue, for the deployment's owner (#2219).

`CurrentAppAdmin` alone, never a `Perm`: the queue is the deployment's, not an
organization's, and the decision for #2219 was one view for the owner rather
than a per-organization or per-member one. Every write is audited by the service.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import BackgroundJobSvc, CurrentAppAdmin
from app.db.models.background_job import JobStatus
from app.schemas.background_job import (
    ActivityWindow,
    BackgroundJobList,
    BackgroundJobRead,
    BackgroundJobsActivity,
    BackgroundJobsOverview,
    BackgroundKindRead,
    JobPool,
    PauseKind,
)

router = APIRouter()


@router.get("", response_model=BackgroundJobsOverview)
async def background_jobs_overview(service: BackgroundJobSvc, _: CurrentAppAdmin) -> Any:
    """How many jobs are in each state, which kinds are paused, who is alive, what is scheduled."""
    return await service.overview()


@router.get("/activity", response_model=BackgroundJobsActivity)
async def background_jobs_activity(
    service: BackgroundJobSvc, _: CurrentAppAdmin, window: ActivityWindow = "day"
) -> Any:
    """What finished over the last day (hourly) or week (six-hourly), by kind, and the wait now."""
    return await service.activity(window)


@router.get("/jobs", response_model=BackgroundJobList)
async def list_background_jobs(
    service: BackgroundJobSvc,
    _: CurrentAppAdmin,
    status: JobStatus | None = None,
    kind: str | None = None,
    pool: JobPool | None = None,
    organization_id: UUID | None = None,
    before: datetime | None = None,
    before_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    """Jobs newest first; pass a page's `next_before` and `next_before_id` for the next one."""
    return await service.list_jobs(
        status=status,
        kind=kind,
        pool=pool,
        organization_id=organization_id,
        before=None if before is None or before_id is None else (before, before_id),
        limit=limit,
    )


@router.post("/jobs/{job_id}/retry", response_model=BackgroundJobRead)
async def retry_background_job(
    job_id: UUID, service: BackgroundJobSvc, admin: CurrentAppAdmin
) -> Any:
    """Give a dead job a fresh set of attempts."""
    return await service.retry(job_id, actor_user_id=admin.id)


@router.post("/jobs/{job_id}/cancel", response_model=BackgroundJobRead)
async def cancel_background_job(
    job_id: UUID, service: BackgroundJobSvc, admin: CurrentAppAdmin
) -> Any:
    """Withdraw a job that has not started."""
    return await service.cancel(job_id, actor_user_id=admin.id)


@router.post("/kinds/{kind}/pause", response_model=BackgroundKindRead)
async def pause_background_kind(
    kind: str, data: PauseKind, service: BackgroundJobSvc, admin: CurrentAppAdmin
) -> Any:
    """Stop workers claiming a kind of job until it is resumed."""
    return await service.pause_kind(kind, reason=data.reason, actor_user_id=admin.id)


@router.post("/kinds/{kind}/resume", response_model=BackgroundKindRead)
async def resume_background_kind(
    kind: str,
    service: BackgroundJobSvc,
    admin: CurrentAppAdmin,
    organization_id: UUID | None = Query(
        None, description="The organization it was paused for; leave out for the whole kind"
    ),
) -> Any:
    """Let workers claim a paused kind again, in one organization or everywhere."""
    return await service.resume_kind(kind, organization_id=organization_id, actor_user_id=admin.id)
