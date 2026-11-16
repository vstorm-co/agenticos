"""Join the channel/decision train with the released coding-task history.

Both branches start at resource icons. Keeping both upgrade paths lets an
existing deployment, or a local channel test database, reach the same head
without renumbering a revision that has already been applied.
"""

revision: str = "0329_merge_channel_and_coding"
down_revision: tuple[str, str] = (
    "0328_agent_task_boards",
    "0323_coding_revert_admission",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
