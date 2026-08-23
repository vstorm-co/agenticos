"""A trigger portal's grant lives in mcp_connections, marked for what it is

Revision ID: 0054_portal_connections
Revises: 0053_polled_trigger_no_secret
Create Date: 2026-08-21

A polled portal reads a third-party account: Gmail is `users.history.list`
against a mailbox somebody consented to. That grant needs a sealed OAuth payload,
the scopes it was granted, a refresh spent under a row lock with an expiry skew,
somewhere to stage a consent that has not landed, and a status - all of which
`mcp_connections` already has and has right.

So this adds one column rather than a second table, and MCP becomes a *consumer*
of the table rather than its owner - what the triggers plan called Phase 0. A
second table would have been a second copy of the part of this product that is
hardest to get right, and the two would drift on the first provider that rotates
refresh tokens.

- `purpose` - `mcp` for every existing row, `portal` for a grant. Every MCP-facing
  read filters on it, because a Gmail grant is not a server anybody should be
  offered to bind an agent to.
- `portal_key` - which portal the grant is for, and the key the poller and the
  trigger card look one up by.
- `poll_cursor` / `polled_at` - where a polled portal's reader has got to, and
  when it last asked.

The org-name unique index becomes `scope = 'org' AND purpose = 'mcp'`: that
constraint exists because a server's name becomes an agent's tool prefix, which a
portal grant never is. A new partial unique index takes its place for grants - one
per portal per organization, so re-consenting replaces rather than adding a second
mailbox nothing could choose between.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0054_portal_connections"
down_revision = "0053_polled_trigger_no_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("purpose", sa.String(length=16), nullable=False, server_default="mcp"),
    )
    op.add_column("mcp_connections", sa.Column("portal_key", sa.String(length=64), nullable=True))
    op.add_column("mcp_connections", sa.Column("poll_cursor", postgresql.JSONB(), nullable=True))
    op.add_column(
        "mcp_connections", sa.Column("polled_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Named the way this metadata's convention names one, so `alembic check`
    # sees the model's index and this one as the same object.
    op.create_index("mcp_connections_purpose_idx", "mcp_connections", ["purpose"])
    op.create_check_constraint(
        "ck_mcp_connection_purpose", "mcp_connections", "purpose IN ('mcp', 'portal')"
    )
    op.create_check_constraint(
        "ck_mcp_connection_portal_key",
        "mcp_connections",
        "(purpose = 'portal') = (portal_key IS NOT NULL)",
    )
    # The name constraint is about an agent's tool prefix, which a grant is not.
    op.drop_index("uq_mcp_connections_org_name", table_name="mcp_connections")
    op.create_index(
        "uq_mcp_connections_org_name",
        "mcp_connections",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("scope = 'org' AND purpose = 'mcp'"),
    )
    op.create_index(
        "uq_mcp_connections_org_portal",
        "mcp_connections",
        ["organization_id", "portal_key"],
        unique=True,
        postgresql_where=sa.text("purpose = 'portal'"),
    )


def downgrade() -> None:
    """The grants go with the column.

    A `portal` row is not an MCP server and cannot be left behind as one: without
    `purpose` every read would find it, and the Builder would offer a mailbox
    grant as a server with no tools. There is nothing else to do with it, and the
    consent it holds is re-obtainable by connecting again.
    """
    op.execute("DELETE FROM mcp_connections WHERE purpose = 'portal'")
    op.drop_index("uq_mcp_connections_org_portal", table_name="mcp_connections")
    op.drop_index("uq_mcp_connections_org_name", table_name="mcp_connections")
    op.create_index(
        "uq_mcp_connections_org_name",
        "mcp_connections",
        ["organization_id", "name"],
        unique=True,
        postgresql_where=sa.text("scope = 'org'"),
    )
    op.drop_constraint("ck_mcp_connection_portal_key", "mcp_connections", type_="check")
    op.drop_constraint("ck_mcp_connection_purpose", "mcp_connections", type_="check")
    op.drop_index("mcp_connections_purpose_idx", table_name="mcp_connections")
    op.drop_column("mcp_connections", "polled_at")
    op.drop_column("mcp_connections", "poll_cursor")
    op.drop_column("mcp_connections", "portal_key")
    op.drop_column("mcp_connections", "purpose")
