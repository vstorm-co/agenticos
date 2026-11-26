"""Join the console and Matrix upgrade paths without changing applied revisions.

Both branches may already exist on stable or preview deployments. Retaining
their identities lets either database reach one head without restamping history.
"""

revision: str = "0346_merge_console_matrix"
down_revision: tuple[str, str] = (
    "0345_merge_mcp_and_personal",
    "0345_matrix_channel",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
