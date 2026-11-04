"""Store an approval step's proposal, the approved final text and whether it was edited.

Existing requests become plain ones: not editable, no proposal, not edited.

Revision ID: 0233_workflow_approval_proposal
Revises: 0232_workflow_input_bytes
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0233_workflow_approval_proposal"
down_revision: str | None = "0232_workflow_input_bytes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_approvals",
        sa.Column("editable", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "workflow_approvals",
        sa.Column("proposal_format", sa.String(length=16), server_default="text", nullable=False),
    )
    op.add_column(
        "workflow_approvals", sa.Column("proposal_label", sa.String(length=80), nullable=True)
    )
    op.add_column("workflow_approvals", sa.Column("proposal", sa.Text(), nullable=True))
    op.add_column("workflow_approvals", sa.Column("final", sa.Text(), nullable=True))
    op.add_column(
        "workflow_approvals",
        sa.Column("edited", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        "ck_workflow_approval_proposal_format",
        "workflow_approvals",
        "proposal_format IN ('text', 'markdown')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_approval_proposal_format", "workflow_approvals", type_="check")
    for column in ("edited", "final", "proposal", "proposal_label", "proposal_format", "editable"):
        op.drop_column("workflow_approvals", column)
