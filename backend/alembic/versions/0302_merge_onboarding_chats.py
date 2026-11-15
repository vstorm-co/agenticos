"""Join the released chat schema with the existing onboarding history.

Keep the preview revisions intact: either the released chat head or an already
applied onboarding head must upgrade without replaying its own column additions.
The branches change separate tables and meet at this explicit merge revision.
"""

revision: str = "0302_merge_onboarding_chats"
down_revision: tuple[str, str] = ("0301_conversation_forks", "0301_merge_onboarding")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
