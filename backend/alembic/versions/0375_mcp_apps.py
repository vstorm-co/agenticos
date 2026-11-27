"""Show the MCP Apps pages of tools in web chat, per connection (#3450).

`mcp_connections.mcp_apps` is the switch, off on every existing row: a page is
the server operator's code, run in the reader's browser, so somebody who
manages the connection turns it on - the same reasoning that keeps
`include_instructions` off.

`tool_calls.mcp_app` keeps what the page needs to be drawn again when the
conversation is reopened: its `ui://` address, the call's input, the server's
whole result and the connection to read the page from. Not the page itself - a
page is the server's to serve (and can be megabytes), so it is read again on
every load. Null on every existing row, which is a call with no page.

Revision ID: 0375_mcp_apps
Revises: 0374_case_from_conversation
Create Date: 2026-11-26 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0375_mcp_apps"
down_revision: str | None = "0374_case_from_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("mcp_apps", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "tool_calls",
        sa.Column("mcp_app", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tool_calls", "mcp_app")
    op.drop_column("mcp_connections", "mcp_apps")
