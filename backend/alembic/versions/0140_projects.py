"""Projects: a shared container, instructions and the chats held in them.

Revision ID: 0140_projects
Revises: 0139_external_agents
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0140_projects"
down_revision: str | None = "0139_external_agents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("default_agent_id", sa.UUID(), nullable=True),
        sa.Column("backend", sa.String(length=16), nullable=False),
        sa.Column("sandbox_connection_id", sa.UUID(), nullable=True),
        sa.Column("runtime", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "backend IN ('state', 'service')", name=op.f("projects_ck_project_backend_check")
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("projects_ck_project_visibility_check"),
        ),
        sa.ForeignKeyConstraint(
            ["default_agent_id"],
            ["agents.id"],
            name=op.f("projects_default_agent_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("projects_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("projects_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sandbox_connection_id"],
            ["sandbox_connections.id"],
            name=op.f("projects_sandbox_connection_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("projects_pkey")),
    )
    op.create_index(
        op.f("projects_organization_id_idx"), "projects", ["organization_id"], unique=False
    )
    op.create_index(op.f("projects_owner_user_id_idx"), "projects", ["owner_user_id"], unique=False)
    # Deleting a connection finds the projects on it through this column.
    op.create_index(
        op.f("projects_sandbox_connection_id_idx"),
        "projects",
        ["sandbox_connection_id"],
        unique=False,
    )
    op.add_column("agent_workspaces", sa.Column("project_id", sa.UUID(), nullable=True))
    op.alter_column("agent_workspaces", "agent_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        op.f("agent_workspaces_project_id_idx"), "agent_workspaces", ["project_id"], unique=False
    )
    op.create_foreign_key(
        op.f("agent_workspaces_project_id_fkey"),
        "agent_workspaces",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("conversations", sa.Column("project_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("conversations_project_id_idx"), "conversations", ["project_id"], unique=False
    )
    op.create_foreign_key(
        op.f("conversations_project_id_fkey"),
        "conversations",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("conversations_project_id_fkey"), "conversations", type_="foreignkey")
    op.drop_index(op.f("conversations_project_id_idx"), table_name="conversations")
    op.drop_column("conversations", "project_id")
    op.drop_constraint(
        op.f("agent_workspaces_project_id_fkey"), "agent_workspaces", type_="foreignkey"
    )
    op.drop_index(op.f("agent_workspaces_project_id_idx"), table_name="agent_workspaces")
    # A project's container belongs to no agent, and the column cannot go back
    # to NOT NULL with those rows in it; the projects they belonged to go too.
    op.execute("DELETE FROM agent_workspaces WHERE agent_id IS NULL")
    op.alter_column("agent_workspaces", "agent_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("agent_workspaces", "project_id")
    op.drop_index(op.f("projects_sandbox_connection_id_idx"), table_name="projects")
    op.drop_index(op.f("projects_owner_user_id_idx"), table_name="projects")
    op.drop_index(op.f("projects_organization_id_idx"), table_name="projects")
    op.drop_table("projects")
