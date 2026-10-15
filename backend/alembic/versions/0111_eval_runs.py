"""Eval runs: an agent answering a dataset version, its arms and every attempt.

`eval_runs` is one run as a person started it - the agent, the dataset version,
the environment lending its test connections, the scoring frozen at start and
the estimate consented to, and - once it ended - its verdict, kept for the
listings. `eval_run_arms` is each configuration that answers
the cases: a published version, a frozen draft or a spec a caller handed over,
on one model, as the candidate or the baseline. An arm reused from an earlier
run points at it instead of answering again. `eval_run_cases` is one attempt of
one case on one arm, with a copy of the answer and the calls, because a case run
keeps no transcript.

`case_scores.eval_run_id`, which scoring's migration adds without a target,
gets its foreign key here: a score goes with the eval run that produced it
(`CASCADE`); a score taken by hand has none.

Every table is new and the column was already nullable, so nothing is
backfilled. The downgrade drops what was added and loses every eval run and
its results; the column stays, as scoring's.

Revision ID: 0111_eval_runs
Revises: 0108_eval_scoring
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0111_eval_runs"
down_revision: str | None = "0108_eval_scoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("paired", sa.Boolean(), nullable=False),
        sa.Column("from_recordings", sa.Boolean(), nullable=False),
        sa.Column("live_reads", sa.Boolean(), nullable=False),
        sa.Column("reruns", sa.Integer(), nullable=False),
        sa.Column("scoring", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scoring_hash", sa.String(length=64), nullable=False),
        sa.Column("estimate_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("rerun_ceiling_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outcome_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('manual', 'gate')", name=op.f("eval_runs_ck_eval_run_purpose_check")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'cancelled', 'failed', 'budget_exceeded')",
            name=op.f("eval_runs_ck_eval_run_status_check"),
        ),
        sa.CheckConstraint(
            "reruns BETWEEN 0 AND 5", name=op.f("eval_runs_ck_eval_run_reruns_check")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name=op.f("eval_runs_agent_id_fkey"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("eval_runs_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("eval_runs_dataset_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("eval_runs_dataset_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["agent_environments.id"],
            name=op.f("eval_runs_environment_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("eval_runs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_runs_pkey")),
    )
    op.create_index(
        op.f("eval_runs_dataset_version_id_idx"), "eval_runs", ["dataset_version_id"], unique=False
    )
    op.create_index(
        op.f("eval_runs_organization_id_idx"), "eval_runs", ["organization_id"], unique=False
    )
    op.create_index(
        "ix_eval_runs_agent_created",
        "eval_runs",
        ["organization_id", "agent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_eval_runs_dataset_created", "eval_runs", ["dataset_id", "created_at"], unique=False
    )
    op.create_table(
        "eval_run_arms",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("eval_run_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_profile_id", sa.UUID(), nullable=True),
        sa.Column("model_label", sa.String(length=255), nullable=False),
        sa.Column("reused_from_arm_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "(source = 'version') = (spec IS NULL)",
            name=op.f("eval_run_arms_ck_eval_run_arm_spec_check"),
        ),
        sa.CheckConstraint(
            "role IN ('candidate', 'baseline')",
            name=op.f("eval_run_arms_ck_eval_run_arm_role_check"),
        ),
        sa.CheckConstraint(
            "source IN ('version', 'draft', 'explicit')",
            name=op.f("eval_run_arms_ck_eval_run_arm_source_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("eval_run_arms_agent_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name=op.f("eval_run_arms_eval_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_profile_id"],
            ["model_profiles.id"],
            name=op.f("eval_run_arms_model_profile_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("eval_run_arms_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reused_from_arm_id"],
            ["eval_run_arms.id"],
            name=op.f("eval_run_arms_reused_from_arm_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_run_arms_pkey")),
        sa.UniqueConstraint("eval_run_id", "position", name="uq_eval_run_arm_position"),
    )
    op.create_index(
        op.f("eval_run_arms_agent_version_id_idx"),
        "eval_run_arms",
        ["agent_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("eval_run_arms_organization_id_idx"),
        "eval_run_arms",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "eval_run_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("eval_run_id", sa.UUID(), nullable=False),
        sa.Column("arm_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("case_revision_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("agent_run_id", sa.UUID(), nullable=True),
        sa.Column("case_score_id", sa.UUID(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("cost_is_partial", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'skipped')",
            name=op.f("eval_run_cases_ck_eval_run_case_status_check"),
        ),
        sa.CheckConstraint(
            "attempt >= 0", name=op.f("eval_run_cases_ck_eval_run_case_attempt_check")
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            name=op.f("eval_run_cases_agent_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["arm_id"],
            ["eval_run_arms.id"],
            name=op.f("eval_run_cases_arm_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_revision_id"],
            ["dataset_cases.id"],
            name=op.f("eval_run_cases_case_revision_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["case_score_id"],
            ["case_scores.id"],
            name=op.f("eval_run_cases_case_score_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_runs.id"],
            name=op.f("eval_run_cases_eval_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("eval_run_cases_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("eval_run_cases_pkey")),
        sa.UniqueConstraint("arm_id", "case_id", "attempt", name="uq_eval_run_case_attempt"),
    )
    op.create_index(
        op.f("eval_run_cases_agent_run_id_idx"), "eval_run_cases", ["agent_run_id"], unique=False
    )
    op.create_index(
        op.f("eval_run_cases_case_revision_id_idx"),
        "eval_run_cases",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("eval_run_cases_organization_id_idx"),
        "eval_run_cases",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_eval_run_cases_org_running",
        "eval_run_cases",
        ["organization_id"],
        unique=False,
        postgresql_where="status = 'running'",
    )
    op.create_index(
        "ix_eval_run_cases_run_status",
        "eval_run_cases",
        ["eval_run_id", "status", "position"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("case_scores_eval_run_id_fkey"),
        "case_scores",
        "eval_runs",
        ["eval_run_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("case_scores_eval_run_id_fkey"), "case_scores", type_="foreignkey")
    op.drop_index("ix_eval_run_cases_run_status", table_name="eval_run_cases")
    op.drop_index(
        "ix_eval_run_cases_org_running",
        table_name="eval_run_cases",
        postgresql_where="status = 'running'",
    )
    op.drop_index(op.f("eval_run_cases_organization_id_idx"), table_name="eval_run_cases")
    op.drop_index(op.f("eval_run_cases_case_revision_id_idx"), table_name="eval_run_cases")
    op.drop_index(op.f("eval_run_cases_agent_run_id_idx"), table_name="eval_run_cases")
    op.drop_table("eval_run_cases")
    op.drop_index(op.f("eval_run_arms_organization_id_idx"), table_name="eval_run_arms")
    op.drop_index(op.f("eval_run_arms_agent_version_id_idx"), table_name="eval_run_arms")
    op.drop_table("eval_run_arms")
    op.drop_index("ix_eval_runs_dataset_created", table_name="eval_runs")
    op.drop_index("ix_eval_runs_agent_created", table_name="eval_runs")
    op.drop_index(op.f("eval_runs_organization_id_idx"), table_name="eval_runs")
    op.drop_index(op.f("eval_runs_dataset_version_id_idx"), table_name="eval_runs")
    op.drop_table("eval_runs")
