"""Agent workspaces - the files an agent keeps between turns

Revision ID: 0002_agent_workspaces
Revises: 0001_baseline
Create Date: 2026-08-03

Two things live in this table and they are not the same shape, which is why
`files` is nullable rather than defaulted:

* a `state` workspace *is* the row - `files` holds the document the in-memory
  backend produces, which is JSON by construction so that it can;
* a container-backed one is bookkeeping beside a workspace the sandbox service
  holds, and carries a `session_id` instead.

The unique constraint names the organization as well as the key. The key already
encodes it, so this is redundant on purpose: a cross-tenant collision becomes
impossible rather than merely improbable, and "impossible" is the property worth
paying an index for on a table with one row per warm conversation.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002_agent_workspaces"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_ref", sa.String(length=128), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=16), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("bytes_total", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="agent_workspaces_agent_id_fkey", ondelete="CASCADE"
        ),
        # CASCADE rather than SET NULL: these files were produced inside that
        # conversation and are shown as part of it, so deleting the thread has to
        # take them with it. A user who deletes a chat has not asked to keep the
        # spreadsheet they uploaded to it.
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="agent_workspaces_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="agent_workspaces_organization_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="agent_workspaces_pkey"),
        sa.UniqueConstraint("organization_id", "scope_key", name="uq_agent_workspace_scope"),
    )
    op.create_index(
        op.f("ix_agent_workspaces_agent_id"), "agent_workspaces", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_workspaces_conversation_id"),
        "agent_workspaces",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_workspaces_organization_id"),
        "agent_workspaces",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_workspaces_owner_ref"), "agent_workspaces", ["owner_ref"], unique=False
    )
    op.create_index(
        op.f("ix_agent_workspaces_scope_key"), "agent_workspaces", ["scope_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_workspaces_scope_key"), table_name="agent_workspaces")
    op.drop_index(op.f("ix_agent_workspaces_owner_ref"), table_name="agent_workspaces")
    op.drop_index(op.f("ix_agent_workspaces_organization_id"), table_name="agent_workspaces")
    op.drop_index(op.f("ix_agent_workspaces_conversation_id"), table_name="agent_workspaces")
    op.drop_index(op.f("ix_agent_workspaces_agent_id"), table_name="agent_workspaces")
    op.drop_table("agent_workspaces")
