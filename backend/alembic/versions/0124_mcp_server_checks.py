"""Record what the catalog check found per MCP listing, and a category for the mirror (#2103).

`mcp_server_checks` holds one row per listing the check reached - the curated
catalog by key, the registry mirror by its registry name - and starts empty:
until a check has run or its bundled snapshot has been seeded, every listing is
simply unchecked, which is what it was before this table existed.

`mcp_registry_servers.category` is `other` for every existing row; the next
`mcp-registry-sync` fills it from each listing's own words.

Revision ID: 0124_mcp_server_checks
Revises: 0123_assistant_mark_path
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0124_mcp_server_checks"
down_revision: str | None = "0123_assistant_mark_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_server_checks",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("auth", sa.String(length=8), nullable=True),
        sa.Column("tools", sa.Integer(), nullable=True),
        sa.Column("read_only_tools", sa.Integer(), nullable=True),
        sa.Column("duplicate_of", sa.String(length=255), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key", name="mcp_server_checks_pkey"),
    )
    op.create_index("mcp_server_checks_outcome_idx", "mcp_server_checks", ["outcome"])
    op.add_column(
        "mcp_registry_servers",
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
    )


def downgrade() -> None:
    op.drop_column("mcp_registry_servers", "category")
    op.drop_index("mcp_server_checks_outcome_idx", table_name="mcp_server_checks")
    op.drop_table("mcp_server_checks")
