"""retain direct workflow provider spend

Revision ID: 0227_workflow_node_spend
Revises: 0226_workflow_child_cost
Create Date: 2026-10-24 16:30:58.620724

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0227_workflow_node_spend"
down_revision: str | Sequence[str] | None = "0226_workflow_child_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_node_spend",
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("cost_is_partial", sa.Boolean(), nullable=False),
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
            name=op.f("workflow_node_spend_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("attempt_id", name=op.f("workflow_node_spend_pkey")),
    )
    op.create_index(
        "ix_workflow_node_spend_org_created",
        "workflow_node_spend",
        ["organization_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_node_spend_org_created", table_name="workflow_node_spend")
    op.drop_table("workflow_node_spend")
