"""Record when each person last read a conversation, for its unread mark.

`conversation_reads` holds one row per (reader, conversation). Every existing
conversation is marked read for its owner as of now, so the sidebar does not
light every thread up the first time it reads the mark.

Revision ID: 0127_conversation_reads
Revises: 0126_drop_queue_while_working
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0127_conversation_reads"
down_revision: str | None = "0126_drop_queue_while_working"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_reads",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "conversation_id"),
    )
    op.create_index(
        "conversation_reads_conversation_id_idx",
        "conversation_reads",
        ["conversation_id"],
    )
    op.execute(
        "INSERT INTO conversation_reads (user_id, conversation_id) "
        "SELECT user_id, id FROM conversations WHERE user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("conversation_reads_conversation_id_idx", table_name="conversation_reads")
    op.drop_table("conversation_reads")
