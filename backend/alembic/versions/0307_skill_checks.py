"""Check a skill change on every agent of its line.

`skill_checks` holds one candidate text of a skill and the line it would change;
`skill_check_agents` one row per agent of that line, with the eval runs that
measured it and what they found. A skill's own test questions are a dataset
bound to the skill (`datasets.skill_id`, one per skill).

`skill_proposals.source` says what wrote a proposal - an agent's workspace, the
assistant, or a library sync - now that a library sync of a skill some agent
follows waits as a proposal instead of being written.

`eval_run_arms.skill_versions` records the stored skill versions an arm's agent
was served, so a cached baseline is reused only for an arm served the same ones.
Existing arms are left null and are never reused for an agent that binds a skill:
one cache miss each, instead of a backfill that would have to guess.

Revision ID: 0307_skill_checks
Revises: 0306_skill_versions
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0307_skill_checks"
down_revision: str | None = "0306_skill_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fork_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_description", sa.String(length=500), nullable=False),
        sa.Column("candidate_content", sa.Text(), nullable=False),
        sa.Column("candidate_resources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("candidate_hash", sa.String(length=64), nullable=False),
        sa.Column("description_changed", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "excluded_conversation_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "skill_set_case_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=True),
        sa.Column("applied_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_unknown_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("at_most_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('quick', 'thorough')", name="ck_skill_check_mode"),
        sa.CheckConstraint(
            "source IN ('manual', 'proposal', 'session')", name="ck_skill_check_source"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'cancelled', 'applied', 'forked', 'discarded')",
            name="ck_skill_check_status",
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN ('passed', 'blocked', 'no_better', 'needs_ack')",
            name="ck_skill_check_verdict",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN "
            "('improve_further', 'apply', 'apply_and_pin', 'fork_for_helped', 'discard')",
            name="ck_skill_check_outcome",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["skill_id", "organization_id"],
            ["skills.id", "skills.organization_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["fork_id", "organization_id"],
            ["skill_forks.id", "skill_forks.organization_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id", "organization_id"],
            ["skill_versions.id", "skill_versions.organization_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["applied_version_id"], ["skill_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["proposal_id"], ["skill_proposals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["acknowledged_unknown_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_skill_checks_tenant"),
    )
    op.create_index(
        "ix_skill_checks_skill", "skill_checks", ["organization_id", "skill_id", "created_at"]
    )
    op.create_index(
        "ix_skill_checks_running",
        "skill_checks",
        ["status"],
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "skill_check_agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("check_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=True),
        sa.Column("via_specialist", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("unknown_reason", sa.String(length=24), nullable=True),
        sa.Column("sample", sa.String(length=16), nullable=True),
        sa.Column(
            "sample_case_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True
        ),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_version", sa.Integer(), nullable=True),
        sa.Column("skill_set_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fixed", sa.Integer(), nullable=False),
        sa.Column("broken", sa.Integer(), nullable=False),
        sa.Column("held_out", sa.Integer(), nullable=False),
        sa.Column("fixed_confirmed", sa.Integer(), nullable=False),
        sa.Column("regressions_confirmed", sa.Integer(), nullable=False),
        sa.Column("noisy", sa.Boolean(), nullable=False),
        sa.Column("expected_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("at_most_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'better', 'no_change', 'within_noise', "
            "'worse', 'unknown')",
            name="ck_skill_check_agent_state",
        ),
        sa.CheckConstraint(
            "unknown_reason IS NULL OR unknown_reason IN ('no_questions', 'no_access', "
            "'no_budget', 'no_published_version', 'inconclusive', 'failed')",
            name="ck_skill_check_agent_reason",
        ),
        sa.CheckConstraint(
            "sample IS NULL OR sample IN ('own_questions', 'skill_set_only')",
            name="ck_skill_check_agent_sample",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["check_id", "organization_id"],
            ["skill_checks.id", "skill_checks.organization_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_set_run_id"], ["eval_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dataset_run_id"], ["eval_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("check_id", "agent_id", name="uq_skill_check_agents_agent"),
    )
    op.create_index(
        "ix_skill_check_agents_agent", "skill_check_agents", ["organization_id", "agent_id"]
    )
    op.create_index(
        "ix_skill_check_agents_skill_set_run", "skill_check_agents", ["skill_set_run_id"]
    )
    op.create_index("ix_skill_check_agents_dataset_run", "skill_check_agents", ["dataset_run_id"])

    op.add_column("datasets", sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "datasets_skill_id_fkey", "datasets", "skills", ["skill_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(
        "uq_datasets_skill",
        "datasets",
        ["organization_id", "skill_id"],
        unique=True,
        postgresql_where=sa.text("skill_id IS NOT NULL"),
    )

    op.add_column("skill_proposals", sa.Column("source", sa.String(length=16), nullable=True))
    op.add_column(
        "eval_run_arms",
        sa.Column("skill_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_run_arms", "skill_versions")
    op.drop_column("skill_proposals", "source")
    op.drop_index("uq_datasets_skill", table_name="datasets")
    op.drop_constraint("datasets_skill_id_fkey", "datasets", type_="foreignkey")
    op.drop_column("datasets", "skill_id")
    op.drop_index("ix_skill_check_agents_dataset_run", table_name="skill_check_agents")
    op.drop_index("ix_skill_check_agents_skill_set_run", table_name="skill_check_agents")
    op.drop_index("ix_skill_check_agents_agent", table_name="skill_check_agents")
    op.drop_table("skill_check_agents")
    op.drop_index("ix_skill_checks_running", table_name="skill_checks")
    op.drop_index("ix_skill_checks_skill", table_name="skill_checks")
    op.drop_table("skill_checks")
