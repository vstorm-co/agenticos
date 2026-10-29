"""Read existing channel threads again with their original message timestamps.

Earlier backfills discarded each post's timestamp. A previously stamped thread
must be read once more by the timestamp-preserving reader, following
0068_reread_channel_threads.py. Otherwise the conversations that exposed the
relative-time bug retain the incomplete context forever. No messages are deleted;
each active thread incurs one extra history read on its next turn.

Revision ID: 0179_reread_thread_timestamps
Revises: 0178_project_workspace_moves
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0179_reread_thread_timestamps"
down_revision: str | None = "0178_project_workspace_moves"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE channel_sessions SET thread_backfilled_at = NULL WHERE thread_backfilled_at IS NOT NULL"
    )


def downgrade() -> None:
    """Keep the honest unknown state; original stamps cannot be reconstructed."""
