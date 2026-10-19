"""The background job queue that replaces Prefect (#2219).

Four tables. `background_jobs` is the queue: a job is written in the
transaction of the change that asks for it, claimed `FOR UPDATE SKIP LOCKED`,
and counts its attempt at the claim so a job that kills its worker cannot be
handed out for ever. `background_schedules` holds where each declared schedule
is up to. `background_task_kinds` is the circuit breaker per kind of job.
`background_workers` is who is alive, for the panel and the health probe.

The indexes follow the queries: the claim and the rescuer each read a partial
index the size of the live queue, not of the history; the two partial unique
indexes are what make "one waiting copy" and "one running copy" facts of the
database rather than checks a race could slip between.

Revision ID: 0145_background_jobs
Revises: 0144_pending_sandbox_destroys
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0145_background_jobs"
down_revision: str | None = "0144_pending_sandbox_destroys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("pool", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("concurrency_key", sa.String(length=255), nullable=True),
        sa.Column("schedule_name", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "pool IN ('agent', 'ingest', 'system')", name=op.f("background_jobs_pool_check")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'dead', 'cancelled')",
            name=op.f("background_jobs_status_check"),
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 2", name=op.f("background_jobs_priority_check")),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("background_jobs_max_attempts_check")),
        sa.PrimaryKeyConstraint("id", name=op.f("background_jobs_pkey")),
    )
    op.create_index(
        op.f("background_jobs_organization_id_idx"), "background_jobs", ["organization_id"]
    )
    op.create_index(
        "background_jobs_claim_idx",
        "background_jobs",
        ["pool", "priority", "run_after", "id"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "background_jobs_lease_idx",
        "background_jobs",
        ["lease_until"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "background_jobs_dedupe_key_idx",
        "background_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status = 'queued' AND dedupe_key IS NOT NULL"),
    )
    op.create_index(
        "background_jobs_concurrency_key_idx",
        "background_jobs",
        ["concurrency_key"],
        unique=True,
        postgresql_where=sa.text("status = 'running' AND concurrency_key IS NOT NULL"),
    )
    op.create_index(
        "background_jobs_status_created_idx",
        "background_jobs",
        ["status", sa.text("created_at DESC")],
    )
    op.create_index(
        "background_jobs_schedule_idx",
        "background_jobs",
        ["schedule_name"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "background_schedules",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("overlap", sa.String(length=8), server_default="skip", nullable=False),
        sa.Column("misfire", sa.String(length=8), server_default="latest", nullable=False),
        sa.Column("grace_seconds", sa.Integer(), server_default="60", nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "interval_seconds > 0", name=op.f("background_schedules_interval_seconds_check")
        ),
        sa.CheckConstraint(
            "overlap IN ('skip', 'queue', 'allow')", name=op.f("background_schedules_overlap_check")
        ),
        sa.CheckConstraint(
            "misfire IN ('latest', 'skip')", name=op.f("background_schedules_misfire_check")
        ),
        sa.CheckConstraint(
            "grace_seconds >= 0", name=op.f("background_schedules_grace_seconds_check")
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("background_schedules_pkey")),
    )

    op.create_table(
        "background_task_kinds",
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("consecutive_deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_lost", sa.Integer(), server_default="0", nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("kind", name=op.f("background_task_kinds_pkey")),
    )

    op.create_table(
        "background_workers",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("pools", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("background_workers_pkey")),
    )
    op.create_index(
        op.f("background_workers_heartbeat_at_idx"), "background_workers", ["heartbeat_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("background_workers_heartbeat_at_idx"), table_name="background_workers")
    op.drop_table("background_workers")
    op.drop_table("background_task_kinds")
    op.drop_table("background_schedules")
    op.drop_index("background_jobs_schedule_idx", table_name="background_jobs")
    op.drop_index("background_jobs_status_created_idx", table_name="background_jobs")
    op.drop_index("background_jobs_concurrency_key_idx", table_name="background_jobs")
    op.drop_index("background_jobs_dedupe_key_idx", table_name="background_jobs")
    op.drop_index("background_jobs_lease_idx", table_name="background_jobs")
    op.drop_index("background_jobs_claim_idx", table_name="background_jobs")
    op.drop_index(op.f("background_jobs_organization_id_idx"), table_name="background_jobs")
    op.drop_table("background_jobs")
