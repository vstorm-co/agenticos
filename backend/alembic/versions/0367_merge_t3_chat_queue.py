"""Join the chat queue and source-link fix with the upstream and thread histories.

The merge preserves both parent revisions and applies no schema changes itself.
"""

revision: str = "0367_merge_t3_chat_queue"
down_revision: tuple[str, str] = (
    "0366_merge_t3_thread_context",
    "0358_defer_dataset_source_links",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
