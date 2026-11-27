"""Join the upstream 1.94.0/1.95.0 history with the t3 history.

The merge preserves both parent revisions and applies no schema changes itself.
"""

revision: str = "0375_merge_t3_v1950"
down_revision: tuple[str, str] = (
    "0374_case_from_conversation",
    "0367_merge_t3_chat_queue",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
