"""Store the files a workflow run makes, so a `FileRef` names something (#1791).

`workflow_files` is what a `FileRef` resolves to: which organization and run a
file belongs to, the step that made it, and where storage keeps its bytes. A
file is run-scoped, and a step reads one only if its own run made it or was
started with it. The table is new, so no existing row changes; the downgrade
drops it, and the stored objects it named go unreferenced.

Revision ID: 0112_workflow_files
Revises: 0111_workflow_exposures
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0112_workflow_files"
down_revision: str | Sequence[str] | None = "0111_workflow_exposures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_run_id", sa.UUID(), nullable=False),
        sa.Column("producing_node_run_id", sa.UUID(), nullable=True),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "byte_size >= 0", name=op.f("workflow_files_ck_workflow_file_byte_size_check")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_files_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["producing_node_run_id"],
            ["node_runs.id"],
            name=op.f("workflow_files_producing_node_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            name=op.f("workflow_files_workflow_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_files_pkey")),
    )
    op.create_index(
        op.f("workflow_files_organization_id_idx"),
        "workflow_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_files_workflow_run_id_idx"),
        "workflow_files",
        ["workflow_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("workflow_files_workflow_run_id_idx"), table_name="workflow_files")
    op.drop_index(op.f("workflow_files_organization_id_idx"), table_name="workflow_files")
    op.drop_table("workflow_files")
