"""Bind project routines explicitly and retain idempotent preset installations."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0277_project_tracking"
down_revision: str | None = "0276_routine_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers", sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "agent_triggers_project_id_fkey",
        "agent_triggers",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("agent_triggers_project_id_idx", "agent_triggers", ["project_id"])
    op.create_table(
        "project_tracking",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("virtual_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "trigger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_triggers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_tracking_owner"),
    )


def downgrade() -> None:
    op.drop_table("project_tracking")
    op.drop_index("agent_triggers_project_id_idx", table_name="agent_triggers")
    op.drop_constraint("agent_triggers_project_id_fkey", "agent_triggers", type_="foreignkey")
    op.drop_column("agent_triggers", "project_id")
