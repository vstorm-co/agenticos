"""Which organization MCP connection served a tool call (#2072).

A server's call log found its calls by the tool-name prefix the connection's
name produces. A member's own connection to the same service carries the same
name, so its calls - the tool, the agent, the time - were listed under the
organization's server for whoever manages it. The connection is now recorded
on the call when the run writes it.

Calls recorded before this column have none and are left out of the log rather
than guessed at by prefix: an empty log is incomplete, a guessed one is wrong.
`SET NULL` on delete, so removing a connection keeps the conversation's record.

Revision ID: 0118_tool_call_mcp_connection
Revises: 0117_group_budgets
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0118_tool_call_mcp_connection"
down_revision: str | None = "0117_group_budgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("mcp_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "tool_calls_mcp_connection_id_fkey",
        "tool_calls",
        "mcp_connections",
        ["mcp_connection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("tool_calls_mcp_connection_id_idx", "tool_calls", ["mcp_connection_id"])


def downgrade() -> None:
    op.drop_index("tool_calls_mcp_connection_id_idx", table_name="tool_calls")
    op.drop_constraint("tool_calls_mcp_connection_id_fkey", "tool_calls", type_="foreignkey")
    op.drop_column("tool_calls", "mcp_connection_id")
