"""Agent registry: agents and their published versions

Revision ID: 0032_agents
Revises: 0031_credentials
Create Date: 2026-07-26

An agent is data, not code. `agents` holds the thing people name, own and
share; `agent_versions` holds the frozen specs that actually ran.

Splitting them is what makes run history honest: a run records the version, so
"why did it answer that last Tuesday" stays answerable after the agent has been
edited a dozen times.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0032_agents"
down_revision = "0031_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("draft_spec", JSONB, nullable=False, server_default="{}"),
        # No foreign key to agent_versions: versions reference agents, and a
        # mutual constraint would force deferred checks on every insert for no
        # benefit. The service keeps the pointer valid.
        sa.Column("current_version_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # The slug is an @mention handle on chat platforms; a duplicate would
        # route messages to the wrong agent.
        sa.UniqueConstraint("organization_id", "slug", name="uq_agent_org_slug"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_agent_status"),
        sa.CheckConstraint("visibility IN ('private', 'team', 'org')", name="ck_agent_visibility"),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])
    op.create_index("ix_agents_owner_user_id", "agents", ["owner_user_id"])
    op.create_index("ix_agents_slug", "agents", ["slug"])
    op.create_index("ix_agents_status", "agents", ["status"])

    op.create_table(
        "agent_versions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "published_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_version_number"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])
    op.create_index("ix_agent_versions_organization_id", "agent_versions", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_versions_organization_id", table_name="agent_versions")
    op.drop_index("ix_agent_versions_agent_id", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_slug", table_name="agents")
    op.drop_index("ix_agents_owner_user_id", table_name="agents")
    op.drop_index("ix_agents_organization_id", table_name="agents")
    op.drop_table("agents")
