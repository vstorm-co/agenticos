"""Bind personal Google grants to the organization whose OAuth client issued them.

Legacy grants have no verifiable source tenant and require reconnecting. No tenant
is inferred from a user's current membership or copied credential.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0293_connected_account_sources"
down_revision: str = "0292_merge_connected_accounts"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column(
            "account_source_organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_index("uq_connected_accounts_user_email", table_name="mcp_connections")
    op.create_index(
        "uq_connected_accounts_user_email",
        "mcp_connections",
        ["user_id", "catalog_key", "account_source_organization_id", "account_email"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text(
            "purpose = 'account' AND scope = 'user' AND account_email IS NOT NULL"
        ),
    )


def downgrade() -> None:
    # Old builds cannot enforce the source tenant and cannot represent the same
    # address linked through multiple tenants. Disconnect grants rather than
    # lending a copied organization credential through their global lookup.
    op.execute("DELETE FROM mcp_connections WHERE purpose = 'account' AND scope = 'user'")
    op.drop_index("uq_connected_accounts_user_email", table_name="mcp_connections")
    op.create_index(
        "uq_connected_accounts_user_email",
        "mcp_connections",
        ["user_id", "catalog_key", "account_email"],
        unique=True,
        postgresql_where=sa.text(
            "purpose = 'account' AND scope = 'user' AND account_email IS NOT NULL"
        ),
    )
    op.drop_column("mcp_connections", "account_source_organization_id")
