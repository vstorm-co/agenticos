"""Improvement sessions: the Improve pipeline's state, rounds and candidate batches (#2385).

A session runs Improve, the policy filter and a paired check in the background
and stops at a checked proposal, so its state has to outlive the request and
the worker: `improvement_runs` holds where it is and what it is pinned to, and
`improvement_iterations` holds each round's children and verdict. At most one
session per agent is queued or running, enforced by a partial unique index so
two concurrent starts cannot both get in.

The authoring tables learn which session a request or a batch belongs to, and a
batch gets the status `candidate`: the session's proposal lives beside a
person's open batch, never replacing it, until the session is ready. A
downgrade deletes candidate batches (their hunks cascade) before narrowing the
status CHECK, since no earlier revision can read them.

Revision ID: 0180_improvement_sessions
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0180_improvement_sessions"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "'queued', 'running', 'ready', 'stopped', 'failed', 'cancelled', 'stale', "
    "'accepted', 'published', 'rejected'"
)
_STAGES = "'analyzing', 'proposing', 'filtering', 'evaluating', 'judging'"
_STOP_REASONS = (
    "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', "
    "'permission', 'stale', 'stalled', 'proposal', 'eval', 'superseded'"
)
_VERDICTS = "'better', 'no_change', 'regression', 'inconclusive'"
_BATCH_CHECK = "spec_proposal_batches_ck_spec_proposal_batch_status_check"


def _uuid() -> postgresql.UUID[object]:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "improvement_runs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("agent_id", _uuid(), nullable=False),
        sa.Column("created_by_user_id", _uuid(), nullable=True),
        sa.Column("created_by_api_key_id", _uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("base_version_id", _uuid(), nullable=True),
        sa.Column("base_draft_hash", sa.String(length=64), nullable=False),
        sa.Column("dataset_id", _uuid(), nullable=True),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column("suite_id", _uuid(), nullable=True),
        sa.Column("scoring_hash", sa.String(length=64), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("estimate_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("budget_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("spent_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("best_iteration_id", _uuid(), nullable=True),
        sa.Column("stop_reason", sa.String(length=16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("stage_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"status IN ({_STATUSES})",
            name=op.f("improvement_runs_ck_improvement_run_status_check"),
        ),
        sa.CheckConstraint(
            f"stage IS NULL OR stage IN ({_STAGES})",
            name=op.f("improvement_runs_ck_improvement_run_stage_check"),
        ),
        sa.CheckConstraint(
            f"stop_reason IS NULL OR stop_reason IN ({_STOP_REASONS})",
            name=op.f("improvement_runs_ck_improvement_run_stop_reason_check"),
        ),
        sa.CheckConstraint(
            "max_iterations BETWEEN 1 AND 10 AND iteration BETWEEN 1 AND max_iterations",
            name=op.f("improvement_runs_ck_improvement_run_iterations_check"),
        ),
        sa.CheckConstraint(
            "estimate_usd >= 0 AND budget_usd >= 0 AND spent_usd >= 0",
            name=op.f("improvement_runs_ck_improvement_run_money_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("improvement_runs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("improvement_runs_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("improvement_runs_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_api_key_id"],
            ["api_keys.id"],
            name=op.f("improvement_runs_created_by_api_key_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["agent_versions.id"],
            name=op.f("improvement_runs_base_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("improvement_runs_dataset_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["eval_suites.id"],
            name=op.f("improvement_runs_suite_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("improvement_runs_pkey")),
    )
    op.create_index(
        op.f("improvement_runs_organization_id_idx"), "improvement_runs", ["organization_id"]
    )
    op.create_index(
        "ix_improvement_runs_agent",
        "improvement_runs",
        ["organization_id", "agent_id", "created_at"],
    )
    op.create_index(
        "uq_improvement_runs_active",
        "improvement_runs",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_improvement_runs_open",
        "improvement_runs",
        ["status"],
        postgresql_where=sa.text("status IN ('queued', 'running', 'ready')"),
    )

    op.create_table(
        "improvement_iterations",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("organization_id", _uuid(), nullable=False),
        sa.Column("run_id", _uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("authoring_request_id", _uuid(), nullable=True),
        sa.Column("batch_id", _uuid(), nullable=True),
        sa.Column("candidate_spec_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "dropped_hunk_ids",
            postgresql.ARRAY(_uuid()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "dropped", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("eval_run_ids", postgresql.ARRAY(_uuid()), server_default="{}", nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("verdict_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"verdict IS NULL OR verdict IN ({_VERDICTS})",
            name=op.f("improvement_iterations_ck_improvement_iteration_verdict_check"),
        ),
        sa.CheckConstraint(
            "number >= 1", name=op.f("improvement_iterations_ck_improvement_iteration_number_check")
        ),
        sa.CheckConstraint(
            "cost_usd >= 0", name=op.f("improvement_iterations_ck_improvement_iteration_cost_check")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("improvement_iterations_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["improvement_runs.id"],
            name=op.f("improvement_iterations_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["authoring_request_id"],
            ["authoring_requests.id"],
            name=op.f("improvement_iterations_authoring_request_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["spec_proposal_batches.id"],
            name=op.f("improvement_iterations_batch_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("improvement_iterations_pkey")),
        sa.UniqueConstraint("run_id", "number", name="uq_improvement_iterations_number"),
    )
    op.create_index(
        op.f("improvement_iterations_organization_id_idx"),
        "improvement_iterations",
        ["organization_id"],
    )
    op.create_foreign_key(
        op.f("improvement_runs_best_iteration_id_fkey"),
        "improvement_runs",
        "improvement_iterations",
        ["best_iteration_id"],
        ["id"],
        ondelete="SET NULL",
    )

    for table in ("authoring_requests", "spec_proposal_batches"):
        op.add_column(table, sa.Column("improvement_run_id", _uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"{table}_improvement_run_id_fkey"),
            table,
            "improvement_runs",
            ["improvement_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(op.f(f"{table}_improvement_run_id_idx"), table, ["improvement_run_id"])

    op.drop_constraint(op.f(_BATCH_CHECK), "spec_proposal_batches", type_="check")
    op.create_check_constraint(
        op.f(_BATCH_CHECK),
        "spec_proposal_batches",
        "status IN ('open', 'superseded', 'published', 'candidate')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM spec_proposal_batches WHERE status = 'candidate'")
    op.drop_constraint(op.f(_BATCH_CHECK), "spec_proposal_batches", type_="check")
    op.create_check_constraint(
        op.f(_BATCH_CHECK),
        "spec_proposal_batches",
        "status IN ('open', 'superseded', 'published')",
    )
    for table in ("spec_proposal_batches", "authoring_requests"):
        op.drop_index(op.f(f"{table}_improvement_run_id_idx"), table_name=table)
        op.drop_constraint(op.f(f"{table}_improvement_run_id_fkey"), table, type_="foreignkey")
        op.drop_column(table, "improvement_run_id")

    op.drop_constraint(
        op.f("improvement_runs_best_iteration_id_fkey"), "improvement_runs", type_="foreignkey"
    )
    op.drop_index(
        op.f("improvement_iterations_organization_id_idx"), table_name="improvement_iterations"
    )
    op.drop_table("improvement_iterations")
    op.drop_index("ix_improvement_runs_open", table_name="improvement_runs")
    op.drop_index("uq_improvement_runs_active", table_name="improvement_runs")
    op.drop_index("ix_improvement_runs_agent", table_name="improvement_runs")
    op.drop_index(op.f("improvement_runs_organization_id_idx"), table_name="improvement_runs")
    op.drop_table("improvement_runs")
