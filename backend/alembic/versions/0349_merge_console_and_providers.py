"""Join the console release and subscription provider migration branches.

The console branch ends at the Architect avatar backfill; provider revisions
manage personal model credentials and ChatGPT registrations independently.
This join lets the provider release upgrade after the console release.
"""

revision: str = "0349_merge_console_and_providers"
down_revision: tuple[str, str] = (
    "0348_architect_generated_avatar",
    "0348_merge_matrix_and_providers",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
