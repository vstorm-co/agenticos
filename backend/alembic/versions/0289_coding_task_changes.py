"""What a coding-agent task changed, kept for the task's panel (#2480).

- `coding_task_changes`: one row per `run_coding_agent` task that ran at `edit`
  in a conversation - the files it added, changed, removed or renamed, each with
  its part of the patch, bounded where it was captured. The tool call's result,
  which the model reads back on every later turn, names the row rather than
  carrying the patch.

Both parents cascade: deleting the conversation, or the organization, deletes
the change sets with it. Nothing existing is rewritten, so the downgrade drops
the table and loses only what it held.

Revision ID: 0289_coding_task_changes
Revises: 0288_table_default_view
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0289_coding_task_changes"
down_revision: str | Sequence[str] | None = "0288_table_default_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coding_task_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("harness", sa.String(length=20), nullable=False),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("omitted", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("coding_task_changes_conversation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("coding_task_changes_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("coding_task_changes_pkey")),
    )
    op.create_index(
        op.f("coding_task_changes_organization_id_idx"),
        "coding_task_changes",
        ["organization_id"],
    )
    op.create_index(
        op.f("coding_task_changes_conversation_id_idx"),
        "coding_task_changes",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_table("coding_task_changes")
