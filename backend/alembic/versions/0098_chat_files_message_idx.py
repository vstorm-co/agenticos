"""Index `chat_files.message_id`, the column every transcript read joins on.

Every index on the table led with `user_id`, so eager-loading `Message.files`
for a page of messages scanned `chat_files` whole.

Revision ID: 0098_chat_files_message_idx
Revises: 0097_sync_source_state
Create Date: 2026-09-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0098_chat_files_message_idx"
down_revision: str | None = "0097_sync_source_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f("chat_files_message_id_idx"), "chat_files", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("chat_files_message_id_idx"), table_name="chat_files")
