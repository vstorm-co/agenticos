"""A connected account: an OAuth grant a virtual terminal's mount signs in as (#2191).

Revision ID: 0257_connected_accounts
Revises: 0256_discord_role_mappings
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0257_connected_accounts"
down_revision: str | None = "0256_discord_role_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_connections", sa.Column("account_email", sa.String(254), nullable=True))
    for scope, owner in (("user", "user_id"), ("org", "organization_id")):
        op.create_index(
            f"uq_connected_accounts_{scope}_email",
            "mcp_connections",
            [owner, "catalog_key", "account_email"],
            unique=True,
            postgresql_where=sa.text(
                f"purpose = 'account' AND scope = '{scope}' AND account_email IS NOT NULL"
            ),
        )
    op.drop_constraint("ck_mcp_connection_purpose", "mcp_connections", type_="check")
    op.create_check_constraint(
        "ck_mcp_connection_purpose",
        "mcp_connections",
        "purpose IN ('mcp', 'portal', 'account')",
    )


def downgrade() -> None:
    op.drop_index("uq_connected_accounts_user_email", table_name="mcp_connections")
    op.drop_index("uq_connected_accounts_org_email", table_name="mcp_connections")
    op.drop_column("mcp_connections", "account_email")
    op.execute("DELETE FROM mcp_connections WHERE purpose = 'account'")
    op.drop_constraint("ck_mcp_connection_purpose", "mcp_connections", type_="check")
    op.create_check_constraint(
        "ck_mcp_connection_purpose", "mcp_connections", "purpose IN ('mcp', 'portal')"
    )
