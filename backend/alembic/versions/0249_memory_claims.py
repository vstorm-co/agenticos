"""The memory ledger: claims with provenance, and a per-scope change counter (#2090).

Notes (`agent_memory_files`) are unchanged. A claim is one assertion in one scope
with its source, its validity and what it superseded, so a correction keeps the
history it corrects and a consolidated conclusion names what it was drawn from.
`memory_scope_state` is what lets an unchanged scope cost nothing: consolidation
runs only where `revision` is ahead of `consolidated_revision`.

Revision ID: 0249_memory_claims
Revises: 0248_drop_memory_mem0
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0249_memory_claims"
down_revision: str | None = "0248_drop_memory_mem0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_claims",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("subject", sa.String(length=120), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("origin", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("source_conversation_id", sa.UUID(), nullable=True),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column(
            "derived_from",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("consolidation_key", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["memory_claims.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("memory_claims_organization_id_idx", "memory_claims", ["organization_id"])
    op.create_index(
        "ix_memory_claims_scope", "memory_claims", ["organization_id", "scope_key", "status"]
    )
    op.create_index("ix_memory_claims_agent", "memory_claims", ["agent_id"])
    op.create_index(
        "uq_memory_claims_consolidation",
        "memory_claims",
        ["organization_id", "scope_key", "consolidation_key"],
        unique=True,
        postgresql_where=sa.text("consolidation_key IS NOT NULL"),
    )
    op.create_table(
        "memory_scope_state",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consolidated_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consolidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "scope_key"),
    )


def downgrade() -> None:
    op.drop_table("memory_scope_state")
    op.drop_index("uq_memory_claims_consolidation", table_name="memory_claims")
    op.drop_index("ix_memory_claims_agent", table_name="memory_claims")
    op.drop_index("ix_memory_claims_scope", table_name="memory_claims")
    op.drop_index("memory_claims_organization_id_idx", table_name="memory_claims")
    op.drop_table("memory_claims")
