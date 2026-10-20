"""What the Background jobs page reads: the queue, its kinds, its workers and its schedules (#2219)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.db.models.background_job import JobStatus
from app.schemas.base import BaseSchema

JobPool = Literal["agent", "ingest", "system"]
ActivityWindow = Literal["day", "week"]


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
    organization_id: UUID | None = Field(
        description="The organization this breaker is for; null for the whole kind"
    )
    organization_name: str | None = None
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


class FinishedBucketRead(BaseSchema):
    start: datetime = Field(description="The start of the slice")
    succeeded: int
    dead: int
    cancelled: int


class KindActivityRead(BaseSchema):
    kind: str
    pool: str
    finished: int = Field(description="Jobs of this kind that finished in the window")
    dead: int
    run_p50_seconds: float | None = Field(description="Median time from start to finish")
    run_p95_seconds: float | None
    wait_p95_seconds: float | None = Field(
        description="How long a due job waited for a worker, at the 95th percentile"
    )


class BackgroundJobsActivity(BaseSchema):
    """What the queue did over a day or a week: the page's charts."""

    window: ActivityWindow
    bucket_seconds: int = Field(description="The length of one slice: an hour, or six")
    buckets: list[FinishedBucketRead] = Field(
        description="Every slice of the window, oldest first, a quiet one at zero"
    )
    kinds: list[KindActivityRead] = Field(description="Busiest first")
    oldest_wait_seconds: float | None = Field(
        description="How long the longest-waiting due job has waited; null when none is"
    )


class PauseKind(BaseSchema):
    reason: str = Field(min_length=1, max_length=500)
