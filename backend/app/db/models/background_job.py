"""A unit of background work, queued in the database that holds the data it is about (#2219)."""

import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

JobStatus = Literal["queued", "running", "succeeded", "dead", "cancelled"]
JOB_STATUSES: tuple[JobStatus, ...] = get_args(JobStatus)


class BackgroundJob(Base, TimestampMixin):
    """One job: what to run, for whom, and how far it has got.

    A job is written in the transaction of the change that asks for it, so the
    work and the data it reads commit together or not at all - the gap between
    "the upload committed" and "the parse was dispatched" that #417 and #1349
    fell into does not exist here.

    **An attempt is counted when a worker claims the job, not when it fails.**
    `attempts` goes up in the same `UPDATE` that hands the job out, so a job that
    kills its worker - out of memory, a segfault, a `SIGKILL` - has already spent
    the attempt before it could do anything else. Another process then finds the
    lease expired and writes what happened (`last_error`); once `attempts` reaches
    `max_attempts` the job is `dead` and nothing hands it out again. A Celery
    worker once looped on exactly such a job here, redelivering it and dying, and
    recorded nothing because the process that would have was the one that died.

    `attempts` is also the fencing token: a worker settles a job only while the
    row still carries the count it claimed it with, so a worker that lost its
    lease and comes back late cannot overwrite what the job's next holder did.

    `organization_id` has no foreign key on purpose. It is for the panel and its
    filters, and the work that outlives an organization - the cleanup a purge
    leaves behind - must not be deleted with it.
    """

    __tablename__ = "background_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    """Which task this is, as `app/worker/jobs.py` names it."""
    pool: Mapped[str] = mapped_column(String(16), nullable=False)
    """Which workers run it: `agent`, `ingest` or `system`."""
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    """`0` interactive, `1` scheduled, `2` bulk. Lower goes first."""
    status: Mapped[JobStatus] = mapped_column(String(16), nullable=False, server_default="queued")
    payload: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Not before. A retry sets it to when the backoff ends."""
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """At most one *queued* job carries a given key: a second enqueue is dropped."""
    concurrency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """At most one *running* job carries a given key: the rest wait their turn."""
    schedule_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The schedule that fired it, when one did."""
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """A caller's own key for the request this job is: one job per key per organization."""
    result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    """What a job that answers someone - an asynchronous run - finished with."""
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When what a dead or cancelled job left outside the queue was closed.

    Null on such a job until its settler has run - a document left `processing`,
    a sync log left `running` - so a settler that failed, the database down at
    the time, is run again by the rescuer rather than forgotten (Codex, #2248).
    """

    __table_args__ = (
        CheckConstraint("pool IN ('agent', 'ingest', 'system')", name="pool"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead', 'cancelled')", name="status"
        ),
        CheckConstraint("priority BETWEEN 0 AND 2", name="priority"),
        CheckConstraint("max_attempts >= 1", name="max_attempts"),
        # The claim: the next queued job of a pool, by priority and then age.
        # Partial, so the index stays the size of the queue rather than of the
        # history.
        Index(
            "background_jobs_claim_idx",
            "pool",
            "priority",
            "run_after",
            "id",
            postgresql_where=sa_text("status = 'queued'"),
        ),
        # The rescuer: running jobs whose lease has run out.
        Index(
            "background_jobs_lease_idx",
            "lease_until",
            postgresql_where=sa_text("status = 'running'"),
        ),
        Index(
            "background_jobs_dedupe_key_idx",
            "dedupe_key",
            unique=True,
            postgresql_where=sa_text("status = 'queued' AND dedupe_key IS NOT NULL"),
        ),
        Index(
            "background_jobs_concurrency_key_idx",
            "concurrency_key",
            unique=True,
            postgresql_where=sa_text("status = 'running' AND concurrency_key IS NOT NULL"),
        ),
        # The panel's listing, newest first, and the retention sweep's cutoff.
        Index("background_jobs_status_created_idx", "status", sa_text("created_at DESC")),
        Index(
            "background_jobs_idempotency_idx",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "background_jobs_schedule_idx",
            "schedule_name",
            postgresql_where=sa_text("status IN ('queued', 'running')"),
        ),
        # The ends whose settlement is still owed, which the rescuer works through.
        Index(
            "background_jobs_unsettled_idx",
            "finished_at",
            postgresql_where=sa_text("status IN ('dead', 'cancelled') AND settled_at IS NULL"),
        ),
        # What finished in a window: the page's charts and the retention sweep.
        Index(
            "background_jobs_finished_idx",
            "finished_at",
            postgresql_where=sa_text("finished_at IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<BackgroundJob(id={self.id}, kind={self.kind}, status={self.status}, "
            f"attempts={self.attempts}/{self.max_attempts})>"
        )
