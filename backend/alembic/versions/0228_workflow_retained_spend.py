"""Preserve monthly workflow limits when retention deletes run content.

Only amounts and admission timestamps survive, keyed by the deleted run. Existing
live rows remain authoritative; previously deleted fees cannot be reconstructed.

Revision ID: 0228_workflow_retained_spend
Revises: 0227_workflow_node_spend
Create Date: 2026-10-24 17:36:48.909549

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0228_workflow_retained_spend"
down_revision: str | None = "0227_workflow_node_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_retained_spend",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=13, scale=6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_retained_spend_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_retained_spend_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("workflow_retained_spend_pkey")),
    )
    op.create_index(
        "ix_workflow_retained_spend_org_workflow_admitted",
        "workflow_retained_spend",
        ["organization_id", "workflow_id", "admitted_at"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_retained_spend_workflow",
        "workflow_retained_spend",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_retained_spend_workflow", table_name="workflow_retained_spend")
    op.drop_index(
        "ix_workflow_retained_spend_org_workflow_admitted", table_name="workflow_retained_spend"
    )
    op.drop_table("workflow_retained_spend")
