"""A workflow step that waits on a person's decision (`human.approval`).

`workflow_approvals` holds one request per `node_runs` row - what the step asks,
who may decide it, until when - and the decision. It cascades with its
organization, workflow, run and node run; the decider is kept as SET NULL, so
deleting an account does not delete what it decided. The downgrade drops it.

Revision ID: 0114_workflow_approvals
Revises: 0113_table_triggers
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0114_workflow_approvals"
down_revision: str | Sequence[str] | None = "0113_table_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("node_run_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "approver_user_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name=op.f("workflow_approvals_ck_workflow_approval_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("workflow_approvals_decided_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["node_run_id"],
            ["node_runs.id"],
            name=op.f("workflow_approvals_node_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_approvals_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_approvals_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("workflow_approvals_workflow_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_approvals_pkey")),
        sa.UniqueConstraint("node_run_id", name=op.f("workflow_approvals_node_run_id_key")),
    )
    op.create_index(
        "ix_workflow_approvals_org_status",
        "workflow_approvals",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_approvals_workflow_id_idx"),
        "workflow_approvals",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_approvals_workflow_run_id_idx"),
        "workflow_approvals",
        ["workflow_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("workflow_approvals_workflow_run_id_idx"), table_name="workflow_approvals")
    op.drop_index(op.f("workflow_approvals_workflow_id_idx"), table_name="workflow_approvals")
    op.drop_index("ix_workflow_approvals_org_status", table_name="workflow_approvals")
    op.drop_table("workflow_approvals")
