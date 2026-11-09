"""Where a forked conversation came from (#2762).

A fork is a new conversation holding a copy of another's history up to one of
its answers. Two nullable references record the source conversation and that
answer, so its owner can be shown "Forked from ...". Both are `SET NULL`: a fork
owns its copied messages and must outlive the source.

`source_conversation_id` was not reused: workflow threads own it, and it
cascades.

Revision ID: 0301_conversation_forks
Revises: 0300_unfiled_writer_provenance
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0301_conversation_forks"
down_revision: str | None = "0300_unfiled_writer_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("fork_copy_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversations",
        sa.Column("forked_from_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("forked_from_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "conversations_fork_storage_idx",
        "conversations",
        ["organization_id", "user_id"],
        postgresql_where=sa.text("fork_copy_bytes > 0"),
    )
    for column in ("forked_from_conversation_id", "forked_from_message_id"):
        # Indexed for the `SET NULL` as much as for reading: deleting a
        # conversation deletes its messages, and each has to find the forks
        # naming it.
        op.create_index(op.f(f"conversations_{column}_idx"), "conversations", [column])
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
    op.drop_index("conversations_fork_storage_idx", table_name="conversations")
    op.drop_column("conversations", "fork_copy_bytes")
    op.drop_constraint(
        op.f("conversations_forked_from_message_id_fkey"), "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("conversations_forked_from_conversation_id_fkey"), "conversations", type_="foreignkey"
    )
    for column in ("forked_from_message_id", "forked_from_conversation_id"):
        op.drop_index(op.f(f"conversations_{column}_idx"), table_name="conversations")
    op.drop_column("conversations", "forked_from_message_id")
    op.drop_column("conversations", "forked_from_conversation_id")
