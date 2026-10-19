"""Name the account an MCP call acts as on its approval.

Two accounts of one service make "Send mail" a question of which mailbox, and
the approval said only the tool. `account` is the binding's label for the
account, copied when the call is parked; null for every existing row and for
any call that is not an MCP account's.

Revision ID: 0132_tool_approval_account
Revises: 0131_mcp_include_instructions
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0132_tool_approval_account"
down_revision: str | None = "0131_mcp_include_instructions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tool_approvals", sa.Column("account", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_approvals", "account")
