"""Agent environments - named pointers at published versions

Revision ID: 0060_agent_environments
Revises: 0059_drop_conversation_kb_ids
Create Date: 2026-07-30

Publishing used to move one pointer (`agents.current_version_id`) for every
surface at once; an environment is a named pointer at one frozen version, so a
dev bot can exercise v12 while production keeps answering with v11. Exposures
and runs both learn which environment they belong to: an exposure so a bot can
serve a non-default version, a run so history can be filtered by where a
version was when it answered.

The backfill gives every published agent a `production` default pointing at
its current version - after it, "what runs by default" has exactly the same
answer it had before this table existed. `current_version_id` stays as the
denormalized default pointer, kept in sync by publish.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0060_agent_environments"
down_revision = "0059_drop_conversation_kb_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_id", "name", name="uq_environment_agent_name"),
    )
    op.create_index(
        "uq_environment_agent_default",
        "agent_environments",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )

    op.add_column(
        "agent_exposures",
        sa.Column(
            "environment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_environments.id",
                ondelete="SET NULL",
                name="agent_exposures_environment_id_fkey",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "environment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "agent_environments.id",
                ondelete="SET NULL",
                name="agent_runs_environment_id_fkey",
            ),
            nullable=True,
        ),
    )

    # Every published agent gets its production default, pointing at exactly
    # the version it serves today.
    op.execute(
        """
        INSERT INTO agent_environments
            (id, organization_id, agent_id, name, version_id, is_default, created_at)
        SELECT gen_random_uuid(), organization_id, id, 'production',
               current_version_id, true, now()
        FROM agents
        WHERE current_version_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "environment_id")
    op.drop_column("agent_exposures", "environment_id")
    op.drop_index("uq_environment_agent_default", table_name="agent_environments")
    op.drop_table("agent_environments")
