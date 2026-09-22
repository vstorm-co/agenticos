"""Workflows: the graph registry and its published versions (#1786).

Shaped after `agents`/`agent_versions`, not after the virtual-tables tables:
`workflows` is the thing people talk about - a name, an owner, a sharing
state, the draft graph being edited - and `workflow_versions` is one frozen,
published graph. `draft_revision` is `Agent.draft_spec` does not have: a
future autosave issue writes a workflow's draft far more often than the
Builder's occasional agent edit, so the optimistic-concurrency field #1782
proved out for record writes (`expected_revision`/`RevisionConflictError`) is
reused here on the workflow's own draft.

Two tables only, no backfill: both are new, and nothing existing references
either. `current_version_id` on `workflows` carries no foreign key, for the
same reason `agents.current_version_id` does not - `workflow_versions`
references `workflows`, and a mutual constraint would need deferred
constraints on both inserts and deletes for no benefit `create_version`
(insert-then-point) does not already get for free.

Revision ID: 0093_workflows
Revises: 0092_virtual_tables
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0093_workflows"
down_revision: str | Sequence[str] | None = "0092_virtual_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "draft_graph",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("draft_revision", sa.Integer(), nullable=False),
        sa.Column("current_version_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name=op.f("workflows_ck_workflow_status_check"),
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'team', 'org')",
            name=op.f("workflows_ck_workflow_visibility_check"),
        ),
        sa.CheckConstraint(
            "draft_revision >= 0", name=op.f("workflows_ck_workflow_draft_revision_check")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("workflows_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflows_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("workflows_owner_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflows_pkey")),
        sa.UniqueConstraint("organization_id", "slug", name="uq_workflow_org_slug"),
    )
    op.create_index(
        op.f("workflows_organization_id_idx"), "workflows", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("workflows_owner_user_id_idx"), "workflows", ["owner_user_id"], unique=False
    )
    op.create_index(op.f("workflows_slug_idx"), "workflows", ["slug"], unique=False)
    op.create_index(op.f("workflows_status_idx"), "workflows", ["status"], unique=False)
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.Column("budget_limit", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version >= 1", name=op.f("workflow_versions_ck_workflow_version_number_check")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_versions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            name=op.f("workflow_versions_published_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_versions_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_versions_pkey")),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_version_number"),
    )
    op.create_index(
        op.f("workflow_versions_organization_id_idx"),
        "workflow_versions",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("workflow_versions_workflow_id_idx"),
        "workflow_versions",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("workflow_versions_workflow_id_idx"), table_name="workflow_versions")
    op.drop_index(op.f("workflow_versions_organization_id_idx"), table_name="workflow_versions")
    op.drop_table("workflow_versions")
    op.drop_index(op.f("workflows_status_idx"), table_name="workflows")
    op.drop_index(op.f("workflows_slug_idx"), table_name="workflows")
    op.drop_index(op.f("workflows_owner_user_id_idx"), table_name="workflows")
    op.drop_index(op.f("workflows_organization_id_idx"), table_name="workflows")
    op.drop_table("workflows")
