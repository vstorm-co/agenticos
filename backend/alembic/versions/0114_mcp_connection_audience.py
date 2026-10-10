"""An organization MCP connection can be narrowed to groups (#2072).

Revision ID: 0114_mcp_connection_audience
Revises: 0113_test_runs
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0114_mcp_connection_audience"
down_revision: str | None = "0113_test_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("visibility", sa.String(16), nullable=False, server_default="org"),
    )
    op.create_check_constraint(
        op.f("mcp_connections_ck_mcp_connection_visibility_check"),
        "mcp_connections",
        "visibility IN ('private', 'team', 'org')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("mcp_connections_ck_mcp_connection_visibility_check"), "mcp_connections", type_="check"
    )
    op.drop_column("mcp_connections", "visibility")
