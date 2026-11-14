"""Keep message subthreads separate from quoted replies inside their original room.

Revision ID: 0326_room_threads
Revises: 0325_merge_t3_rooms_v173

Existing quote links stay in the main transcript. The new nullable root names a
top-level message in the same conversation; deleting that root removes its thread
rather than moving replies into the main room. No new audience or room is created.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0326_room_threads"
down_revision: str | None = "0325_merge_t3_rooms_v173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("thread_root_message_id", sa.UUID(), nullable=True))
    op.create_unique_constraint(
        "uq_messages_conversation_id_id", "messages", ["conversation_id", "id"]
    )
    op.create_foreign_key(
        "fk_messages_thread_root",
        "messages",
        "messages",
        ["conversation_id", "thread_root_message_id"],
        ["conversation_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("thread_root_not_self", "messages", "thread_root_message_id <> id")
    op.create_index(
        "messages_thread_ordinal_idx",
        "messages",
        ["conversation_id", "thread_root_message_id", "ordinal"],
        postgresql_where=sa.text("thread_root_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM messages WHERE thread_root_message_id IS NOT NULL)")
    ):
        raise RuntimeError(
            "Cannot remove room thread scopes while replies exist; retain a thread-aware app "
            "or restore a matching pre-upgrade backup"
        )
    op.drop_index("messages_thread_ordinal_idx", table_name="messages")
    op.drop_constraint("thread_root_not_self", "messages", type_="check")
    op.drop_constraint("fk_messages_thread_root", "messages", type_="foreignkey")
    op.drop_constraint("uq_messages_conversation_id_id", "messages", type_="unique")
    op.drop_column("messages", "thread_root_message_id")
