"""Join skill versioning and mandatory approval visibility.

Both independent branches start after the shared-page attribution revision;
this merge keeps both upgrade paths and presents one deployment head.
"""

revision: str = "0315_merge_skills_approvals"
down_revision: tuple[str, str] = (
    "0312_skill_check_reasons",
    "0314_tool_approval_always_asks",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
