"""Join the accepted chat queue with the upstream and thread context histories.

The merge preserves both parent revisions and applies no schema changes itself.
"""

revision: str = "0367_merge_t3_chat_queue"
down_revision: tuple[str, str] = (
    "0366_merge_t3_thread_context",
    "0357_accepted_queued_messages",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
