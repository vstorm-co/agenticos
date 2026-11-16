"""Retain configured approval groups independently of their later membership."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0322_workflow_approval_groups"
down_revision: str = "0321_resource_icons"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "workflow_approvals",
        sa.Column("approver_group_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("workflow_approvals", "approver_group_ids")
