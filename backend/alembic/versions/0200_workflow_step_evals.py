"""A model step's evals: the cases it is tried on, and the tries.

`workflow_step_evals` holds each case - an input, the known output of the steps
before, and what the answer should say - and `workflow_eval_runs` which test run
tried which case. Both go with their workflow.

Revision ID: 0200_workflow_step_evals
Revises: 0199_workflow_gmail_trigger
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0200_workflow_step_evals"
down_revision: str | None = "0199_workflow_gmail_trigger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_eval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("node_instance_id", sa.UUID(), nullable=False),
        sa.Column("started_by_user_id", sa.UUID(), nullable=True),
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
            name=op.f("workflow_eval_runs_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"],
            ["users.id"],
            name=op.f("workflow_eval_runs_started_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_eval_runs_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_eval_runs_pkey")),
    )
    op.create_index(
        "ix_workflow_eval_run_step",
        "workflow_eval_runs",
        ["workflow_id", "node_instance_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_eval_runs_organization_id_idx"),
        "workflow_eval_runs",
        ["organization_id"],
        unique=False,
    )
    op.create_table(
        "workflow_step_evals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("node_instance_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("run_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expectation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("workflow_step_evals_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_step_evals_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_step_evals_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_step_evals_pkey")),
    )
    op.create_index(
        "ix_workflow_step_eval_step",
        "workflow_step_evals",
        ["workflow_id", "node_instance_id"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_step_evals_organization_id_idx"),
        "workflow_step_evals",
        ["organization_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("workflow_step_evals_organization_id_idx"), table_name="workflow_step_evals")
    op.drop_index("ix_workflow_step_eval_step", table_name="workflow_step_evals")
    op.drop_table("workflow_step_evals")
    op.drop_index(op.f("workflow_eval_runs_organization_id_idx"), table_name="workflow_eval_runs")
    op.drop_index("ix_workflow_eval_run_step", table_name="workflow_eval_runs")
    op.drop_table("workflow_eval_runs")
