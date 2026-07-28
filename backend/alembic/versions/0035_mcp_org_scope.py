"""MCP connections: organization scope and catalog provenance

Revision ID: 0035_mcp_org
Revises: 0034_skills
Create Date: 2026-07-26

MCP connections were personal only. A published agent cannot depend on whose
session happens to run it, so an agent spec needs connections that belong to the
organization rather than to a member.

Both scopes stay. A developer's personal token should not end up in everyone
else's agents, and an org connection should not vanish when its creator leaves —
which is exactly the distinction ``scope`` records.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0035_mcp_org"
down_revision = "0034_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mcp_connections",
        sa.Column("scope", sa.String(8), nullable=False, server_default="user"),
    )
    op.add_column("mcp_connections", sa.Column("catalog_key", sa.String(64), nullable=True))
    op.create_foreign_key(
        "mcp_connections_organization_id_fkey",
        "mcp_connections",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_mcp_connections_organization_id", "mcp_connections", ["organization_id"])
    op.create_index("ix_mcp_connections_scope", "mcp_connections", ["scope"])
    # Names identify a server to the people configuring agents, so they must be
    # unambiguous within an organization. Personal connections keep the existing
    # per-user uniqueness and are excluded here.
    op.create_index(
        "uq_mcp_connections_org_name",
        "mcp_connections",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("scope = 'org'"),
    )
    op.create_check_constraint(
        "ck_mcp_connection_scope",
        "mcp_connections",
        "scope IN ('user', 'org')",
    )
    op.create_check_constraint(
        "ck_mcp_connection_org_scope_has_org",
        "mcp_connections",
        "scope <> 'org' OR organization_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mcp_connection_org_scope_has_org", "mcp_connections", type_="check")
    op.drop_constraint("ck_mcp_connection_scope", "mcp_connections", type_="check")
    op.drop_index("uq_mcp_connections_org_name", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_scope", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_organization_id", table_name="mcp_connections")
    op.drop_constraint(
        "mcp_connections_organization_id_fkey", "mcp_connections", type_="foreignkey"
    )
    op.drop_column("mcp_connections", "catalog_key")
    op.drop_column("mcp_connections", "scope")
    op.drop_column("mcp_connections", "organization_id")
