"""Join stored workflow scopes with the released onboarding and chat history.

Both feature previews retain their original revision IDs. A deployment that has
already applied either branch upgrades the other once, without replaying data
rewrites or adding its existing columns again.
"""

revision: str = "0303_merge_workflow_onboarding"
down_revision: tuple[str, str] = ("0302_merge_onboarding_chats", "0301_workflow_loop_scope")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
