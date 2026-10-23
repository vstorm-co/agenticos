"""Mark a conversation an organization key's run opened (#2122).

`conversations.origin` is null for every existing conversation - each was opened
in the console or by a channel - and `api` from now on for one an API run opens,
which is what its owner's chat list labels and can leave out.

Revision ID: 0125_conversation_origin
Revises: 0124_mcp_server_checks
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0125_conversation_origin"
down_revision: str | None = "0124_mcp_server_checks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("origin", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "origin")
