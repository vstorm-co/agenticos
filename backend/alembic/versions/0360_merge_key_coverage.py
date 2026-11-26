"""Join coverage reports with the checked instruction-search/key-draft history.

Preserve all applied revision identities while exposing one deployment head.
"""

revision: str = "0360_merge_key_coverage"
down_revision: tuple[str, str] = (
    "0359_merge_search_key_drafts",
    "0355_key_coverage_reports",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
