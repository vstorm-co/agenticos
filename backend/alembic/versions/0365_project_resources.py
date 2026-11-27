"""Group existing resources without copying specs or changing their grants.

Revision ID: 0365_project_resources
Revises: 0364_merge_routine_and_kb
Create Date: 2026-11-24 16:15:47.092477

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0365_project_resources"
down_revision: str | None = "0364_merge_routine_and_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_resources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("workflow_id", sa.UUID(), nullable=True),
        sa.Column("app_id", sa.UUID(), nullable=True),
        sa.Column("table_id", sa.UUID(), nullable=True),
        sa.Column("is_entrypoint", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "NOT is_entrypoint OR workflow_id IS NOT NULL",
            name=op.f("project_resources_ck_project_resource_workflow_entrypoint_check"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(agent_id, workflow_id, app_id, table_id) = 1",
            name=op.f("project_resources_ck_project_resource_one_target_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("project_resources_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["app_id"],
            ["artifacts.id"],
            name=op.f("project_resources_app_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("project_resources_project_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["table_id"],
            ["virtual_tables.id"],
            name=op.f("project_resources_table_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("project_resources_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("project_resources_pkey")),
        sa.UniqueConstraint("project_id", "agent_id", name="uq_project_resource_agent"),
        sa.UniqueConstraint("project_id", "app_id", name="uq_project_resource_app"),
        sa.UniqueConstraint("project_id", "table_id", name="uq_project_resource_table"),
        sa.UniqueConstraint("project_id", "workflow_id", name="uq_project_resource_workflow"),
    )
    op.create_index(
        op.f("project_resources_agent_id_idx"), "project_resources", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("project_resources_app_id_idx"), "project_resources", ["app_id"], unique=False
    )
    op.create_index(
        op.f("project_resources_project_id_idx"), "project_resources", ["project_id"], unique=False
    )
    op.create_index(
        op.f("project_resources_table_id_idx"), "project_resources", ["table_id"], unique=False
    )
    op.create_index(
        op.f("project_resources_workflow_id_idx"),
        "project_resources",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        "uq_project_resource_entrypoint",
        "project_resources",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_entrypoint"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_project_resource_entrypoint",
        table_name="project_resources",
        postgresql_where=sa.text("is_entrypoint"),
    )
    op.drop_index(op.f("project_resources_workflow_id_idx"), table_name="project_resources")
    op.drop_index(op.f("project_resources_table_id_idx"), table_name="project_resources")
    op.drop_index(op.f("project_resources_project_id_idx"), table_name="project_resources")
    op.drop_index(op.f("project_resources_app_id_idx"), table_name="project_resources")
    op.drop_index(op.f("project_resources_agent_id_idx"), table_name="project_resources")
    op.drop_table("project_resources")
