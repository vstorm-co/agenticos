"""What the Background jobs page reads: the queue, its kinds, its workers and its schedules (#2219)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.background_job import JobStatus
from app.schemas.base import BaseSchema

JobPool = Literal["agent", "ingest", "system"]


class BackgroundJobRead(BaseSchema):
    """One job as the deployment's owner sees it. The payload is not shown: it carries ids, not facts."""

    id: UUID
    kind: str
    pool: JobPool
    status: JobStatus
    priority: int
    attempts: int
    max_attempts: int
    organization_id: UUID | None
    schedule_name: str | None
    worker_id: str | None
    last_error: str | None
    run_after: datetime
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class BackgroundJobList(BaseSchema):
    items: list[BackgroundJobRead]
    next_before: datetime | None = Field(
        default=None,
        description="Pass as `before`, with `next_before_id`, for the next page; absent on the last.",
    )
    next_before_id: UUID | None = Field(
        default=None, description="Pass as `before_id` beside `before`."
    )


class BackgroundKindRead(BaseSchema):
    """A kind of job the circuit breaker has an opinion about."""

    kind: str
    consecutive_deaths: int
    lease_lost: int
    paused_at: datetime | None
    paused_reason: str | None


class BackgroundWorkerRead(BaseSchema):
    id: str
    hostname: str
    pools: list[str]
    started_at: datetime
    heartbeat_at: datetime


class BackgroundScheduleRead(BaseSchema):
    name: str
    kind: str
    interval_seconds: int
    next_run_at: datetime
    last_fired_at: datetime | None
    overlap: str
    misfire: str


class BackgroundJobsOverview(BaseSchema):
    """The page's header: how much is where, what is stopped, who is alive, what is next."""

    counts: dict[JobStatus, int]
    kinds: list[BackgroundKindRead]
    workers: list[BackgroundWorkerRead]
    schedules: list[BackgroundScheduleRead]


class PauseKind(BaseSchema):
    reason: str = Field(min_length=1, max_length=500)
