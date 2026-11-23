"""Join instruction search and case-key draft migrations.

Keep both branch histories available to existing databases and expose one head.
"""

revision: str = "0359_merge_search_key_drafts"
down_revision: tuple[str, str] = (
    "0356_improvement_search",
    "0354_case_key_drafts",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
