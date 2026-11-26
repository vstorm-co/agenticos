"""Add immutable sandbox bindings and short-lived Project mount leases.

Revision ID: 0373_project_filesystem_mounts
Revises: 0372_release_train
Create Date: 2026-11-26 14:51:21.603369

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0373_project_filesystem_mounts"
down_revision: str | None = "0372_release_train"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_filesystem_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=True),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("session_name", sa.String(length=64), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("secret_key_version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["sandbox_connections.id"],
            name=op.f("project_filesystem_bindings_connection_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("project_filesystem_bindings_conversation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("project_filesystem_bindings_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["agent_workspaces.id"],
            name=op.f("project_filesystem_bindings_workspace_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("project_filesystem_bindings_pkey")),
        sa.UniqueConstraint(
            "organization_id",
            "connection_id",
            "session_name",
            name="uq_project_filesystem_binding_session",
        ),
        sa.UniqueConstraint("organization_id", "id", name="uq_project_filesystem_binding_tenant"),
    )
    op.create_index(
        op.f("project_filesystem_bindings_connection_id_idx"),
        "project_filesystem_bindings",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_bindings_conversation_id_idx"),
        "project_filesystem_bindings",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_bindings_organization_id_idx"),
        "project_filesystem_bindings",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_bindings_workspace_id_idx"),
        "project_filesystem_bindings",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "project_filesystem_leases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("binding_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("workspace_generation", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("authority_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("project_filesystem_leases_actor_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "binding_id"],
            ["project_filesystem_bindings.organization_id", "project_filesystem_bindings.id"],
            name="fk_project_filesystem_lease_binding_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("project_filesystem_leases_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("project_filesystem_leases_project_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("project_filesystem_leases_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("project_filesystem_leases_pkey")),
    )
    op.create_index(
        op.f("project_filesystem_leases_actor_id_idx"),
        "project_filesystem_leases",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_leases_binding_id_idx"),
        "project_filesystem_leases",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_leases_expires_at_idx"),
        "project_filesystem_leases",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_leases_organization_id_idx"),
        "project_filesystem_leases",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_leases_project_id_idx"),
        "project_filesystem_leases",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("project_filesystem_leases_run_id_idx"),
        "project_filesystem_leases",
        ["run_id"],
        unique=False,
    )
    op.add_column(
        "agent_workspaces",
        sa.Column("filesystem_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_workspaces", "filesystem_metadata")
    op.drop_index(
        op.f("project_filesystem_leases_run_id_idx"), table_name="project_filesystem_leases"
    )
    op.drop_index(
        op.f("project_filesystem_leases_project_id_idx"), table_name="project_filesystem_leases"
    )
    op.drop_index(
        op.f("project_filesystem_leases_organization_id_idx"),
        table_name="project_filesystem_leases",
    )
    op.drop_index(
        op.f("project_filesystem_leases_expires_at_idx"), table_name="project_filesystem_leases"
    )
    op.drop_index(
        op.f("project_filesystem_leases_binding_id_idx"), table_name="project_filesystem_leases"
    )
    op.drop_index(
        op.f("project_filesystem_leases_actor_id_idx"), table_name="project_filesystem_leases"
    )
    op.drop_table("project_filesystem_leases")
    op.drop_index(
        op.f("project_filesystem_bindings_workspace_id_idx"),
        table_name="project_filesystem_bindings",
    )
    op.drop_index(
        op.f("project_filesystem_bindings_organization_id_idx"),
        table_name="project_filesystem_bindings",
    )
    op.drop_index(
        op.f("project_filesystem_bindings_conversation_id_idx"),
        table_name="project_filesystem_bindings",
    )
    op.drop_index(
        op.f("project_filesystem_bindings_connection_id_idx"),
        table_name="project_filesystem_bindings",
    )
    op.drop_table("project_filesystem_bindings")
