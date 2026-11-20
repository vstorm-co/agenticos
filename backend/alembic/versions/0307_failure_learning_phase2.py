"""Failure-learning loop, Phase 2: instruction proposals (#0307).

One table for the proposed change itself - the rule text, what it replaces,
why, and the eval try that evidences it - plus the two foreign keys Phase 1
deferred: `agent_eval_runs.proposal_id` and
`agent_failure_ledger.resolved_proposal_id` now point at the proposals
table, both nullable and SET NULL, so deleting a proposal never deletes a
try or an entry.

This follows the failure-learning tables in `0306_failure_learning_phase1`,
which is chained after the access-hardening migration head. Skill proposals
record the applied content hash and prior content for a one-time rollback.

Revision ID: 0307_failure_learning_phase2
Revises: 0306_failure_learning_phase1
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0307_failure_learning_phase2"
down_revision: str | None = "0306_failure_learning_phase1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_instruction_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("eval_try_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("old_text", sa.Text(), nullable=False),
        sa.Column("new_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("base_agent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("base_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("prior_skill_content", sa.Text(), nullable=True),
        sa.Column("applied_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("applied_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('instructions', 'skill')", name="ck_proposal_target_type"
        ),
        sa.CheckConstraint("status IN ('draft', 'applied', 'rejected')", name="ck_proposal_status"),
        sa.CheckConstraint(
            "(target_type = 'skill' AND skill_id IS NOT NULL) OR "
            "(target_type = 'instructions' AND skill_id IS NULL)",
            name="ck_proposal_skill_target",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_instruction_proposals_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_instruction_proposals_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_entry_id"],
            ["agent_failure_ledger.id"],
            name=op.f("agent_instruction_proposals_ledger_entry_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["eval_try_id"],
            ["agent_eval_runs.id"],
            name=op.f("agent_instruction_proposals_eval_try_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["skills.id"],
            name=op.f("agent_instruction_proposals_skill_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["base_agent_version_id"],
            ["agent_versions.id"],
            name=op.f("agent_instruction_proposals_base_agent_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["applied_version_id"],
            ["agent_versions.id"],
            name=op.f("agent_instruction_proposals_applied_version_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("agent_instruction_proposals_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("agent_instruction_proposals_decided_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reverted_by_user_id"],
            ["users.id"],
            name=op.f("agent_instruction_proposals_reverted_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_instruction_proposals_pkey")),
    )
    op.create_index(
        op.f("agent_instruction_proposals_organization_id_idx"),
        "agent_instruction_proposals",
        ["organization_id"],
    )
    op.create_index(
        "ix_proposal_org_agent_status",
        "agent_instruction_proposals",
        ["organization_id", "agent_id", "status"],
    )

    # The two references Phase 1 left as plain UUIDs, now foreign keys.
    op.create_foreign_key(
        op.f("agent_eval_runs_proposal_id_fkey"),
        "agent_eval_runs",
        "agent_instruction_proposals",
        ["proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("agent_failure_ledger_resolved_proposal_id_fkey"),
        "agent_failure_ledger",
        "agent_instruction_proposals",
        ["resolved_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("agent_failure_ledger_resolved_proposal_id_fkey"),
        "agent_failure_ledger",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("agent_eval_runs_proposal_id_fkey"), "agent_eval_runs", type_="foreignkey"
    )
    op.drop_index("ix_proposal_org_agent_status", table_name="agent_instruction_proposals")
    op.drop_index(
        op.f("agent_instruction_proposals_organization_id_idx"),
        table_name="agent_instruction_proposals",
    )
    op.drop_table("agent_instruction_proposals")
