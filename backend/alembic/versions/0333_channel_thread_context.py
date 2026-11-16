"""Persist external thread context once in the shared conversation history.

Legacy sessions start at their last received turn: old native message ids were
not retained, so reimporting their entire history would duplicate compacted turns.
New sessions import a bounded initial thread and every later turn imports its delta.
"""

import sqlalchemy as sa

from alembic import op

revision = "0333_channel_thread_context"
down_revision = "0332_routine_activation_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("channel_stop_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "channel_message_sources",
        sa.Column(
            "conversation_id",
            sa.UUID(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("post_id", sa.String(255), primary_key=True),
    )
    op.add_column(
        "channel_sessions",
        sa.Column("thread_context_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE channel_sessions SET thread_context_at = last_message_at WHERE thread_history_version > 0"
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "channel_stop_requested_at")
    op.drop_column("channel_sessions", "thread_context_at")
    op.drop_table("channel_message_sources")
