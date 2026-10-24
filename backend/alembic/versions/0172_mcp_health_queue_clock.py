"""Give bounded MCP health checks a fair queue independent of OAuth activity.

OAuth renewal updates the account's displayed check timestamp. Reusing that
column to admit a limited health batch would let frequently renewed accounts
stay behind static servers forever. A dedicated epoch-initialized clock gives
never-checked rows priority and a partial index bounds oldest-first admission.

Revision ID: 0172_mcp_health_queue_clock
Revises: 0171_workspace_recovery_parent
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0172_mcp_health_queue_clock"
down_revision: str | None = "0171_workspace_recovery_parent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column(
            "health_checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("'1970-01-01 00:00:00+00'::timestamptz"),
        ),
    )
    op.create_index(
        "mcp_connections_health_queue_idx",
        "mcp_connections",
        ["health_checked_at", "id"],
        postgresql_where=sa.text("scope = 'org' AND purpose = 'mcp' AND is_enabled IS true"),
    )


def downgrade() -> None:
    op.drop_index("mcp_connections_health_queue_idx", table_name="mcp_connections")
    op.drop_column("mcp_connections", "health_checked_at")
