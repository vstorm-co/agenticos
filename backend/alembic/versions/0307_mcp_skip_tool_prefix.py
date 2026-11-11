"""Let an organization connection present its server's own tool names.

Every MCP tool reaches the model as the connection's prefix and the server's
name joined, and a server that prefixes its own tools repeats itself: NetBox's
`netbox_get_objects` arrives as `netbox_netbox_get_objects` (#2881).
`skip_tool_prefix` drops the connection's half, off for every existing row so
no tool name an agent already calls changes.

Revision ID: 0307_mcp_skip_tool_prefix
Revises: 0306_shared_page_attribution
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0307_mcp_skip_tool_prefix"
down_revision: str | None = "0306_shared_page_attribution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("skip_tool_prefix", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "skip_tool_prefix")
