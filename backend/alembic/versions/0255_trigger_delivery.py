"""Where a routine's answer is delivered, and when it ends by itself (#2575).

Revision ID: 0255_trigger_delivery
Revises: 0254_outcomes
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0255_trigger_delivery"
down_revision: str | None = "0254_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("answer_to", sa.String(length=16), server_default="run_log", nullable=False),
    )
    op.add_column("agent_triggers", sa.Column("delivery_conversation_id", sa.UUID(), nullable=True))
    op.add_column("agent_triggers", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "agent_triggers_delivery_conversation_id_fkey",
        "agent_triggers",
        "conversations",
        ["delivery_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_trigger_answer_to",
        "agent_triggers",
        "answer_to IN ('run_log', 'primary', 'conversation')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_answer_to", "agent_triggers", type_="check")
    op.drop_constraint(
        "agent_triggers_delivery_conversation_id_fkey", "agent_triggers", type_="foreignkey"
    )
    op.drop_column("agent_triggers", "ends_at")
    op.drop_column("agent_triggers", "delivery_conversation_id")
    op.drop_column("agent_triggers", "answer_to")
