"""Where a forked conversation came from (#2762).

A fork is a new conversation holding a copy of another's history up to one of
its answers. Two nullable references record the source conversation and that
answer, so its owner can be shown "Forked from ...". Both are `SET NULL`: a fork
owns its copied messages and must outlive the source.

`source_conversation_id` was not reused: workflow threads own it, and it
cascades.

Revision ID: 0258_conversation_forks
Revises: 0257_connected_accounts
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0258_conversation_forks"
down_revision: str | None = "0257_connected_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("forked_from_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("forked_from_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("conversations_forked_from_conversation_id_idx"),
        "conversations",
        ["forked_from_conversation_id"],
    )
    op.create_foreign_key(
        op.f("conversations_forked_from_conversation_id_fkey"),
        "conversations",
        "conversations",
        ["forked_from_conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("conversations_forked_from_message_id_fkey"),
        "conversations",
        "messages",
        ["forked_from_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("conversations_forked_from_message_id_fkey"), "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("conversations_forked_from_conversation_id_fkey"), "conversations", type_="foreignkey"
    )
    op.drop_index(op.f("conversations_forked_from_conversation_id_idx"), table_name="conversations")
    op.drop_column("conversations", "forked_from_message_id")
    op.drop_column("conversations", "forked_from_conversation_id")
