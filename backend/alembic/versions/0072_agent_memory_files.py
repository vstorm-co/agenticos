"""Agent memory files — an agent's own named store, scoped and trust-tiered.

The file half of the `memory` capability (#788). Unlike a context file (0030),
which a person authors and binds to many agents read-only, a memory file is the
agent's *own*: the agent writes and edits it through a runtime tool, and it is
addressed by its agent plus the end-user partition it was written in, never
bound by id.

Two columns are the capability's safety surface rather than plain metadata:

`origin` is the trust tier — `operator` (written by a person through the
management API) or `agent` (written by a tool mid-run) — CHECK-constrained
because only `operator` content is ever injected into instructions; an
agent-authored row is untrusted input reachable only as a tool result.

`end_user_scope_key` is the per-end-user partition: `NULL` is the one shared
store per (organization, agent); a non-null `user:<id>`/`chan:<id>` is one
end-user's private store. Because `NULL` means "the shared store" and not "a
missing value", the uniqueness of a name within a scope has to treat two shared
rows as colliding — hence `NULLS NOT DISTINCT`, which plain SQL uniqueness does
not do (two `NULL` scopes would read as distinct and let one name exist twice).
This is the first `NULLS NOT DISTINCT` constraint in the schema; it needs
PostgreSQL 15+, which the deployment already requires (pgvector/pgvector:pg16).

Revision ID: 0072_agent_memory_files
Revises: 0071_mcp_connection_catalog_key
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0072_agent_memory_files"
down_revision: str | None = "0071_mcp_connection_catalog_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("end_user_scope_key", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "origin IN ('operator', 'agent')",
            name=op.f("agent_memory_files_ck_agent_memory_file_origin_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("agent_memory_files_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("agent_memory_files_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("agent_memory_files_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "agent_id",
            "end_user_scope_key",
            "name",
            name="uq_agent_memory_file_scope_name",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        op.f("agent_memory_files_organization_id_idx"),
        "agent_memory_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("agent_memory_files_agent_id_idx"),
        "agent_memory_files",
        ["agent_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("agent_memory_files_agent_id_idx"), table_name="agent_memory_files")
    op.drop_index(op.f("agent_memory_files_organization_id_idx"), table_name="agent_memory_files")
    op.drop_table("agent_memory_files")
