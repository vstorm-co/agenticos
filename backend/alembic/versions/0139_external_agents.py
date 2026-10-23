"""Agents served over A2A, and remote A2A agents to delegate to (#2092).

Revision ID: 0139_external_agents
Revises: 0138_visuals
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0139_external_agents"
down_revision: str | None = "0138_visuals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_agents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("card_url", sa.String(length=1000), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1000), nullable=False),
        sa.Column("card", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("external_agents_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("external_agents_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["secret_id"],
            ["organization_secrets.id"],
            name=op.f("external_agents_secret_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("external_agents_pkey")),
        sa.UniqueConstraint("organization_id", "slug", name="uq_external_agent_org_slug"),
    )
    op.create_index(
        op.f("external_agents_organization_id_idx"),
        "external_agents",
        ["organization_id"],
        unique=False,
    )
    # Deleting a secret finds the registrations it cascades to through this column.
    op.create_index(
        op.f("external_agents_secret_id_idx"), "external_agents", ["secret_id"], unique=False
    )
    op.add_column(
        "agents",
        sa.Column("a2a_enabled", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agents", "a2a_enabled")
    op.drop_index(op.f("external_agents_secret_id_idx"), table_name="external_agents")
    op.drop_index(op.f("external_agents_organization_id_idx"), table_name="external_agents")
    op.drop_table("external_agents")
