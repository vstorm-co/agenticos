"""A connected account: an OAuth grant a virtual terminal's mount signs in as (#2191).

Revision ID: 0160_connected_accounts
Revises: 0159_default_organization
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0160_connected_accounts"
down_revision: str | None = "0159_default_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_mcp_connection_purpose", "mcp_connections", type_="check")
    op.create_check_constraint(
        "ck_mcp_connection_purpose",
        "mcp_connections",
        "purpose IN ('mcp', 'portal', 'account')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM mcp_connections WHERE purpose = 'account'")
    op.drop_constraint("ck_mcp_connection_purpose", "mcp_connections", type_="check")
    op.create_check_constraint(
        "ck_mcp_connection_purpose", "mcp_connections", "purpose IN ('mcp', 'portal')"
    )
