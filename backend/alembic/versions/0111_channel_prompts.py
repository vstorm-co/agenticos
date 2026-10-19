"""Approvals and questions offered as buttons in a chat (#2064, #2067, #2068).

Revision ID: 0111_channel_prompts
Revises: 0110_organization_assistants
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0111_channel_prompts"
down_revision: str | None = "0110_organization_assistants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("channel_bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform_chat_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column(
            "approval_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_approvals.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("tool_call_id", sa.Text(), nullable=True),
        sa.Column("question_index", sa.Integer(), nullable=True),
        sa.Column("choices", postgresql.JSONB(), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(kind = 'approval' AND approval_id IS NOT NULL)"
            " OR (kind = 'question' AND tool_call_id IS NOT NULL AND question_index IS NOT NULL)",
            name="ck_channel_prompts_kind",
        ),
    )
    op.create_index("ix_channel_prompts_run_call", "channel_prompts", ["run_id", "tool_call_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_prompts_run_call", table_name="channel_prompts")
    op.drop_table("channel_prompts")
