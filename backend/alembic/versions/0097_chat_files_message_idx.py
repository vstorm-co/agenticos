"""The index the transcript read joins on.

`conversation_repo.get_messages_by_conversation` eager-loads `Message.files` on
every read of a thread, which is `WHERE message_id IN (:page of message ids)`
against `chat_files`. Every index on that table led with `user_id`, so opening a
conversation scanned it whole - once per transcript, and again for every run
transcript through `get_messages_by_run`.

Revision ID: 0097_chat_files_message_idx
Revises: 0096_sync_removal
Create Date: 2026-09-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0097_chat_files_message_idx"
down_revision: str | None = "0096_sync_removal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f("chat_files_message_id_idx"), "chat_files", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("chat_files_message_id_idx"), table_name="chat_files")
