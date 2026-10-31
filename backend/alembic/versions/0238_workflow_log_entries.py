"""A workflow's own log: the lines a step's Quick Log writes when it settles.

`workflow_log_entries` holds one row per settled run of a step that carries a
Quick Log: its time, the step as it was named then, the port it left by, its
status, the rendered message, and whether the run was a test or the output
pinned. Rows cascade with their run - so run retention removes them - and with
the workflow and the organization. The downgrade drops the table.

Revision ID: 0238_workflow_log_entries
Revises: 0237_mailbox_poll_interval
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0238_workflow_log_entries"
down_revision: str | Sequence[str] | None = "0237_mailbox_poll_interval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_log_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("node_instance_id", sa.UUID(), nullable=False),
        sa.Column("step_label", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_test", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_log_entries_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            name=op.f("workflow_log_entries_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_log_entries_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_log_entries_pkey")),
    )
    op.create_index(
        "ix_workflow_log_entries_org_workflow_created",
        "workflow_log_entries",
        ["organization_id", "workflow_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index("ix_workflow_log_entries_run", "workflow_log_entries", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_workflow_log_entries_run", table_name="workflow_log_entries")
    op.drop_index("ix_workflow_log_entries_org_workflow_created", table_name="workflow_log_entries")
    op.drop_table("workflow_log_entries")
