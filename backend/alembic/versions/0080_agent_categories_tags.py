"""Editable categories and tags on agents (FA-023, #1592).

Two scalar-array columns on `agents`, for discovery. They are agent-record
metadata, not part of `AgentSpec`, exactly like `avatar_url`/`avatar_color`:
the spec is the versioned, portable definition of what an agent *does* and what
exports to a client's git, and a tag changes neither. Putting them on the spec
would freeze a discovery aid into every published version, force a publish to
retag, and bump `SPEC_VERSION` - so they live on the row, edited by a command
endpoint the way the avatar colour is.

`text[]` rather than JSONB or a join table: an array of short scalars is the
natural shape, gets the `&&` overlap operator the filter needs, and a GIN index
answers that filter directly. A normalized `tags`/`agent_tags` pair would earn
its keep only with a managed per-org vocabulary, rename-propagation or usage
counts - none of which this asks for.

`NOT NULL DEFAULT '{}'` fills every existing row with an empty array in place,
so there is no backfill loop and no nullable ambiguity between "no tags" and
"unset". This is an additive column, not a narrowing rule, so no data migration
is required.

The two `CREATE INDEX ... USING gin` statements take a brief `SHARE` lock on
`agents` while they scan it. `agents` is a low-cardinality table (an organization
holds tens of agents, not millions) and both indexes start empty, so the lock is
negligible; `CONCURRENTLY` is deliberately not used, as it cannot run inside
Alembic's per-revision transaction and no revision here does.

Revision ID: 0080_agent_categories_tags
Revises: 0079_audit_hash_chain
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0080_agent_categories_tags"
down_revision: str | Sequence[str] | None = "0079_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("categories", sa.ARRAY(sa.String(32)), nullable=False, server_default="{}"),
    )
    op.add_column(
        "agents",
        sa.Column("tags", sa.ARRAY(sa.String(32)), nullable=False, server_default="{}"),
    )
    op.create_index("ix_agents_categories", "agents", ["categories"], postgresql_using="gin")
    op.create_index("ix_agents_tags", "agents", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_agents_tags", table_name="agents")
    op.drop_index("ix_agents_categories", table_name="agents")
    op.drop_column("agents", "tags")
    op.drop_column("agents", "categories")
