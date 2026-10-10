"""Mark the credentials the platform mints for its own assistant (#1798).

Revision ID: 0109_internal_api_keys
Revises: 0108_oauth_for_mcp
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0109_internal_api_keys"
down_revision: str | None = "0108_oauth_for_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("internal", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("api_keys", "internal")
