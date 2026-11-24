"""Keep nightly read receipts independent of watches and repeated run endings.

A nullable per-message receipt identifies the person and the source-text digest
a successful look read, without retaining another copy of their text. Old runs
cannot establish which messages were read, so existing rows remain unread and
get one catch-up look under the existing allowance. Downgrade drops only this
internal receipt; message content and run history are retained.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0299_nightly_read_receipt"
down_revision: str = "0298_workflow_question_wait"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("nightly_read_by_user_id", sa.UUID(), nullable=True))
    op.add_column("messages", sa.Column("nightly_read_content_hash", sa.String(64), nullable=True))
    op.create_foreign_key(
        "messages_nightly_read_by_user_id_fkey",
        "messages",
        "users",
        ["nightly_read_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("messages_nightly_read_by_user_id_idx", "messages", ["nightly_read_by_user_id"])


def downgrade() -> None:
    op.drop_index("messages_nightly_read_by_user_id_idx", table_name="messages")
    op.drop_constraint("messages_nightly_read_by_user_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "nightly_read_content_hash")
    op.drop_column("messages", "nightly_read_by_user_id")
