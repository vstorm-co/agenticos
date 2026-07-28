"""MCP connections: who owns an organization one, and how its secret is sealed

Revision ID: 0037_mcp_owner
Revises: 0036_paused
Create Date: 2026-07-27

0035 gave a connection a ``scope`` but left ``user_id`` NOT NULL with an
``ON DELETE CASCADE``, which quietly contradicted the thing that migration set
out to make true: an organization connection that belongs to whoever created it
disappears when they leave, and — worse — is reachable through the personal
``/me/mcp-connections`` routes, which authorize on ``user_id`` alone and demand
no ``connections:manage``. A member could repoint a shared agent's server at
their own host without holding a single organization permission.

So ownership moves. An organization row has no owner (``user_id IS NULL``) and
records its author in ``created_by_user_id``, which nulls rather than cascades.
The two check constraints make the personal routes structurally unable to see an
organization row, rather than relying on every future query remembering a filter.

``secret_key_version`` records which vault master key sealed ``auth_token``.
Personal tokens are Fernet-encrypted with ``SECRET_KEY`` and ignore it;
organization tokens go through ``app.core.vault``, which is bound to the
organization id and needs the version to survive a key rotation.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0037_mcp_owner"
down_revision = "0036_paused"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("created_by_user_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "mcp_connections_created_by_user_id_fkey",
        "mcp_connections",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "mcp_connections",
        sa.Column("secret_key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("mcp_connections", "user_id", nullable=True)
    # Every row that exists today is personal, so both constraints hold before
    # they are added and no backfill is needed.
    op.create_check_constraint(
        "ck_mcp_connection_user_scope_has_user",
        "mcp_connections",
        "scope <> 'user' OR user_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_mcp_connection_org_scope_has_no_user",
        "mcp_connections",
        "scope <> 'org' OR user_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mcp_connection_org_scope_has_no_user", "mcp_connections", type_="check")
    op.drop_constraint("ck_mcp_connection_user_scope_has_user", "mcp_connections", type_="check")
    # An organization connection has no owner, and the column it would have to
    # go back into is about to become NOT NULL. There is no member to attribute
    # it to — inventing one would hand somebody a shared credential — so the
    # rows go. This is the one thing this migration cannot reverse losslessly.
    op.execute("DELETE FROM mcp_connections WHERE scope = 'org'")
    op.alter_column("mcp_connections", "user_id", nullable=False)
    op.drop_column("mcp_connections", "secret_key_version")
    op.drop_constraint(
        "mcp_connections_created_by_user_id_fkey", "mcp_connections", type_="foreignkey"
    )
    op.drop_column("mcp_connections", "created_by_user_id")
