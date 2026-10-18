"""Which earlier message a turn answers, in a chat several people talk in.

Revision ID: 0142_message_reply_to
Revises: 0141_message_author_user
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0142_message_reply_to"
down_revision: str | None = "0141_message_author_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to_message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "messages_reply_to_message_id_fkey",
        "messages",
        "messages",
        ["reply_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Deleting a message makes Postgres find every reply to it, and without an
    # index on the referencing column that is a scan of all messages - per
    # deleted message, when a whole conversation goes.
    op.create_index(
        op.f("messages_reply_to_message_id_idx"),
        "messages",
        ["reply_to_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("messages_reply_to_message_id_idx"), table_name="messages")
    op.drop_constraint("messages_reply_to_message_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "reply_to_message_id")
