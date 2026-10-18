"""Voice conversations: spoken turns on messages (#54).

Each turn of a call is saved as an ordinary message the moment it finishes, so
a crash loses at most the turn in progress. `turn_id` (`<call id>:<n>:<role>`)
identifies a spoken turn within its call, and (conversation_id, turn_id) is
unique so that a retried write - after a timeout, or across a reconnect that
replays its seed - lands once. A partial unique index (`WHERE turn_id IS NOT
NULL`) rather than a constraint: every typed message has no `turn_id`, and an
index over the whole of `messages` - the largest table there is - would be paid
for on every typed turn to guard rows that are never spoken. `interrupted` marks an answer
the caller talked over, whose text is trimmed to roughly what was heard.
Existing rows take the server default `false`. No audio is stored.

Revision ID: 0143_message_voice_turns
Revises: 0142_voice_calls
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0143_message_voice_turns"
down_revision: str | None = "0142_voice_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("turn_id", sa.String(length=80), nullable=True))
    op.add_column(
        "messages",
        sa.Column("interrupted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "uq_messages_conversation_turn",
        "messages",
        ["conversation_id", "turn_id"],
        unique=True,
        postgresql_where=sa.text("turn_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_messages_conversation_turn",
        table_name="messages",
        postgresql_where=sa.text("turn_id IS NOT NULL"),
    )
    op.drop_column("messages", "interrupted")
    op.drop_column("messages", "turn_id")
