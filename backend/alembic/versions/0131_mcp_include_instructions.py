"""Let a connection opt in to its MCP server's own instructions.

A server may answer `initialize` with instructions on how its tools are meant
to be used; Pydantic AI leaves them out unless asked. `include_instructions`
is that ask, per connection, off for every existing row.

Revision ID: 0131_mcp_include_instructions
Revises: 0130_channel_prompt_multi
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0131_mcp_include_instructions"
down_revision: str | None = "0130_channel_prompt_multi"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("include_instructions", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("mcp_connections", "include_instructions")
