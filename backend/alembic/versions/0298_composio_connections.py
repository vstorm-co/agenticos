"""Managed app connections reuse the existing member-owned connection boundary.

Composio holds provider credentials. Only its account/config IDs and verified
status are stored here; an in-flight authorization uses the existing vault-sealed
pending payload, so reconnecting does not replace a working grant prematurely.
Existing MCP and account rows retain their current authentication behavior.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0298_composio_connections"
down_revision: str = "0297_agent_messages"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections", sa.Column("composio_account_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "mcp_connections", sa.Column("composio_auth_config_id", sa.String(128), nullable=True)
    )
    op.add_column("mcp_connections", sa.Column("composio_status", sa.String(32), nullable=True))


def downgrade() -> None:
    # An older runtime does not understand auth_type="composio". Disable the
    # rows before removing their metadata so it cannot treat the stable identity
    # URL as an ordinary server requiring no token. Preserve the member's row.
    # Operators disconnect accounts before rollback to remove provider grants.
    op.execute(
        sa.text("UPDATE mcp_connections SET is_enabled = false WHERE auth_type = 'composio'")
    )
    op.drop_column("mcp_connections", "composio_status")
    op.drop_column("mcp_connections", "composio_auth_config_id")
    op.drop_column("mcp_connections", "composio_account_id")
