"""Record how much an approver changed a proposal, measured once when it was decided.

`edit_ratio` is the share of the proposal the approver changed, between 0 and 1, written
by the decide service in the same update as `final` and `edited`. It is null for a
request that was rejected, never editable, expired, cancelled or still pending - and for
every request decided before this revision: those were never measured, and no backfill
guesses one (a stored ratio is never recomputed, so a guess would stay).

The index serves the approval figures, which read one workflow's requests by the day
they were asked.

Revision ID: 0235_workflow_approval_metrics
Revises: 0234_workflow_outlook_trigger
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0235_workflow_approval_metrics"
down_revision: str | None = "0234_workflow_outlook_trigger"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("workflow_approvals", sa.Column("edit_ratio", sa.Float(), nullable=True))
    op.create_check_constraint(
        "ck_workflow_approval_edit_ratio",
        "workflow_approvals",
        "edit_ratio IS NULL OR (edit_ratio >= 0 AND edit_ratio <= 1)",
    )
    op.create_index(
        "ix_workflow_approvals_org_workflow_created",
        "workflow_approvals",
        ["organization_id", "workflow_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_approvals_org_workflow_created", table_name="workflow_approvals")
    op.drop_constraint("ck_workflow_approval_edit_ratio", "workflow_approvals", type_="check")
    op.drop_column("workflow_approvals", "edit_ratio")
