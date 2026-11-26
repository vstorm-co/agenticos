"""Join the MCP and personal-assistant upgrade paths.

Both branches can already be applied on a deployment or preview database.
Retain their original identities so either one can upgrade to the same head.
"""

revision: str = "0345_merge_mcp_and_personal"
down_revision: tuple[str, str] = ("0344_user_appearance", "0343_bundled_context")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
