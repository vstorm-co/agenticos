"""The public MCP registry as a table, so all of it can be paged.

The mirror shipped as `app/core/catalog/mcp_registry.json` and was searched in
memory, which answers "servers matching 'linear'" and cannot answer "the fourth
page of all of them" without loading 5,703 entries and slicing them. So the
console showed the curated hundred and hid the rest behind a query, which reads
as a catalog of a hundred.

**No `organization_id`, and that is the point.** The skill gallery settled the
neighbouring question the other way: seventy industry skills seeded per tenant
would be seventy rows nobody asked for in every organization on the next deploy,
so that one is opt-in and never seeded. A catalog is not tenant data - it is the
same list for everybody on the box - so one global table is one table rather than
one per tenant, and no organization gains rows it did not ask for.

The primary key is the registry's own reverse-DNS name rather than a uuid: it is
the identity upstream assigns, it is what a refresh matches on, and a surrogate
key would need a unique index on it anyway and then two keys for one identity.

`host` is stored rather than parsed per query, because somebody holding a URL and
wanting the name searches on it, and a LIKE against a substring of `url` cannot
use an index. `synced_at` is what makes a delisted server removable: a row the
current sync did not touch is one upstream no longer lists.

Empty on upgrade. `agenticos cmd mcp-registry-sync` fills it from the bundled
mirror, or from the live registry with `--fetch`, and the console falls back to
the curated catalog alone until it has run - which is what it did before this
table existed, so an install that never syncs is no worse off than it was.

Revision ID: 0070_mcp_registry_servers
Revises: 0069_channel_bot_stt
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0070_mcp_registry_servers"
down_revision: str | None = "0069_channel_bot_stt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_registry_servers",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("mcp_registry_servers_pkey")),
    )
    op.create_index("mcp_registry_servers_name_idx", "mcp_registry_servers", ["name"])
    op.create_index("mcp_registry_servers_host_idx", "mcp_registry_servers", ["host"])
    op.create_index("mcp_registry_servers_synced_at_idx", "mcp_registry_servers", ["synced_at"])


def downgrade() -> None:
    op.drop_index("mcp_registry_servers_synced_at_idx", table_name="mcp_registry_servers")
    op.drop_index("mcp_registry_servers_host_idx", table_name="mcp_registry_servers")
    op.drop_index("mcp_registry_servers_name_idx", table_name="mcp_registry_servers")
    op.drop_table("mcp_registry_servers")
