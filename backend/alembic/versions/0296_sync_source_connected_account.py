"""Allow Google Drive sync sources to use an organization OAuth account."""

import sqlalchemy as sa

from alembic import op

revision: str = "0296_gdrive_oauth"
down_revision: str | None = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("sync_sources", sa.Column("connected_account_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "sync_sources_connected_account_id_fkey",
        "sync_sources",
        "mcp_connections",
        ["connected_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sync_sources_connected_account_id", "sync_sources", ["connected_account_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_sync_sources_connected_account_id", table_name="sync_sources")
    op.drop_constraint("sync_sources_connected_account_id_fkey", "sync_sources", type_="foreignkey")
    op.drop_column("sync_sources", "connected_account_id")
