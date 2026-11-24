"""Failure-learning loop, Phase 1: ledger, eval cases, eval runs (#0306).

Three tables for mining real failures, curating them into a ledger, and
trying instruction changes against eval cases that reproduce them. Mining
itself is a live aggregation over `agent_runs` and `message_ratings` - no
snapshot table - so the only new index on an existing table is the partial
`ix_agent_runs_mining` on `agent_runs`, which serves the mining group-by
(agent and status inside an org window, top-level real runs only).

Proposals and apply land in Phase 2 (migration 0307): the two proposal
references here (`agent_failure_ledger.resolved_proposal_id`,
`agent_eval_runs.proposal_id`) are plain UUID columns until then, and 0305
adds their foreign keys.

This follows both current `t3` heads, `0305a_totp_last_counter` and
`0306_run_retry_link`.

Revision ID: 0306_failure_learning_phase1
Revises: 0305a_totp_last_counter, 0306_run_retry_link
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0306_failure_learning_phase1"
down_revision: str | Sequence[str] | None = (
    "0305a_totp_last_counter",
    "0306_run_retry_link",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_failure_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("pattern_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('agent', 'model')", name="ck_failure_ledger_scope_value"),
        sa.CheckConstraint(
            "status IN ('draft', 'open', 'dismissed', 'resolved')",
            name="ck_failure_ledger_status",
        ),
        sa.CheckConstraint(
            "(scope = 'agent' AND agent_id IS NOT NULL) OR "
            "(scope = 'model' AND agent_id IS NULL AND model IS NOT NULL)",
            name="ck_failure_ledger_scope",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_failure_ledger_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_failure_ledger_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("agent_failure_ledger_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_failure_ledger_pkey")),
    )
    op.create_index(
        op.f("agent_failure_ledger_organization_id_idx"),
        "agent_failure_ledger",
        ["organization_id"],
    )
    op.create_index(op.f("agent_failure_ledger_agent_id_idx"), "agent_failure_ledger", ["agent_id"])
    op.create_index(
        "ix_failure_ledger_org_agent_status",
        "agent_failure_ledger",
        ["organization_id", "agent_id", "status"],
    )
    op.create_index(
        "ix_failure_ledger_org_model_status",
        "agent_failure_ledger",
        ["organization_id", "model", "status"],
    )
    op.create_index(
        "uq_failure_ledger_open_agent",
        "agent_failure_ledger",
        ["organization_id", "agent_id", "pattern_key"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL AND status IN ('draft', 'open')"),
    )
    op.create_index(
        "uq_failure_ledger_open_model",
        "agent_failure_ledger",
        ["organization_id", "model", "pattern_key"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NULL AND status IN ('draft', 'open')"),
    )

    op.create_table(
        "agent_eval_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expectation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_eval_cases_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_eval_cases_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"],
            ["agent_failure_ledger.id"],
            name=op.f("agent_eval_cases_ledger_entry_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_profile_id"],
            ["model_profiles.id"],
            name=op.f("agent_eval_cases_model_profile_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("agent_eval_cases_source_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("agent_eval_cases_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_eval_cases_pkey")),
    )
    op.create_index(
        op.f("agent_eval_cases_organization_id_idx"), "agent_eval_cases", ["organization_id"]
    )
    op.create_index("ix_agent_eval_case_agent", "agent_eval_cases", ["organization_id", "agent_id"])

    op.create_table(
        "agent_eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tested_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("started_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_eval_runs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_eval_runs_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"],
            ["users.id"],
            name=op.f("agent_eval_runs_started_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_skill_id"],
            ["skills.id"],
            name=op.f("agent_eval_runs_target_skill_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_eval_runs_pkey")),
    )
    op.create_index(
        op.f("agent_eval_runs_organization_id_idx"), "agent_eval_runs", ["organization_id"]
    )
    op.create_index(
        "ix_agent_eval_run_agent",
        "agent_eval_runs",
        ["organization_id", "agent_id", "created_at"],
    )

    op.create_index(
        "ix_agent_runs_mining",
        "agent_runs",
        ["organization_id", "agent_id", "status", "started_at"],
        postgresql_where=sa.text("is_test = false AND parent_run_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_mining", table_name="agent_runs")
    op.drop_index("ix_agent_eval_run_agent", table_name="agent_eval_runs")
    op.drop_index(op.f("agent_eval_runs_organization_id_idx"), table_name="agent_eval_runs")
    op.drop_table("agent_eval_runs")
    op.drop_index("ix_agent_eval_case_agent", table_name="agent_eval_cases")
    op.drop_index(op.f("agent_eval_cases_organization_id_idx"), table_name="agent_eval_cases")
    op.drop_table("agent_eval_cases")
    op.drop_index("uq_failure_ledger_open_model", table_name="agent_failure_ledger")
    op.drop_index("uq_failure_ledger_open_agent", table_name="agent_failure_ledger")
    op.drop_index("ix_failure_ledger_org_model_status", table_name="agent_failure_ledger")
    op.drop_index("ix_failure_ledger_org_agent_status", table_name="agent_failure_ledger")
    op.drop_index(op.f("agent_failure_ledger_agent_id_idx"), table_name="agent_failure_ledger")
    op.drop_index(
        op.f("agent_failure_ledger_organization_id_idx"), table_name="agent_failure_ledger"
    )
    op.drop_table("agent_failure_ledger")
