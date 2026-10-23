"""A job's settlement is recorded, and the circuit breaker is per organization (#2248).

Two answers to the Codex review's third round on the job queue:

- `background_jobs.settled_at`: a dead or cancelled job's settler - the code that
  closes a document left `processing` or a sync log left `running` - ran only
  once, in the worker, and a failure there was logged and forgotten. Null now
  marks a settlement still owed, which the rescuer runs again. Every job that
  had already ended is stamped as settled: nothing is owed for it.
- `background_task_kinds` is keyed by kind and organization. One tenant whose
  jobs killed their worker five times paused that kind for every organization;
  now it pauses it for that tenant. A row with no organization still covers the
  whole kind. Existing rows keep it.

Revision ID: 0149_settled_at_org_breaker
Revises: 0148_job_finished_idx
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0149_settled_at_org_breaker"
down_revision: str | None = "0148_job_finished_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "background_jobs", sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE background_jobs SET settled_at = coalesce(finished_at, now()) "
        "WHERE status IN ('dead', 'cancelled')"
    )
    op.create_index(
        "background_jobs_unsettled_idx",
        "background_jobs",
        ["finished_at"],
        postgresql_where=sa.text("status IN ('dead', 'cancelled') AND settled_at IS NULL"),
    )

    op.add_column(
        "background_task_kinds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.add_column(
        "background_task_kinds",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint("background_task_kinds_pkey", "background_task_kinds", type_="primary")
    op.create_primary_key("background_task_kinds_pkey", "background_task_kinds", ["id"])
    op.alter_column("background_task_kinds", "id", server_default=None)
    op.create_foreign_key(
        "background_task_kinds_organization_id_fkey",
        "background_task_kinds",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "background_task_kinds_scope_key",
        "background_task_kinds",
        ["kind", "organization_id"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Back to one row per kind: the deployment-wide rows stay, the
    # per-organization ones go, since the old key has room for one each.
    op.execute("DELETE FROM background_task_kinds WHERE organization_id IS NOT NULL")
    op.drop_constraint("background_task_kinds_scope_key", "background_task_kinds", type_="unique")
    op.drop_constraint(
        "background_task_kinds_organization_id_fkey", "background_task_kinds", type_="foreignkey"
    )
    op.drop_constraint("background_task_kinds_pkey", "background_task_kinds", type_="primary")
    op.create_primary_key("background_task_kinds_pkey", "background_task_kinds", ["kind"])
    op.drop_column("background_task_kinds", "organization_id")
    op.drop_column("background_task_kinds", "id")

    op.drop_index("background_jobs_unsettled_idx", table_name="background_jobs")
    op.drop_column("background_jobs", "settled_at")
