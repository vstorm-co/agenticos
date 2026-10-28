"""Let a `human.approval` step offer the approver several ways to approve.

`choices` holds what the step offered when it asked, as a list of `{id, label}`,
and `choice` the id the approver took. Both are null on every request made
before this revision, and null means "no choices" - the request the approver
approves or rejects as before - so nothing is backfilled.

Revision ID: 0236_workflow_approval_choices
Revises: 0235_workflow_approval_metrics
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0236_workflow_approval_choices"
down_revision: str | None = "0235_workflow_approval_metrics"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("workflow_approvals", sa.Column("choices", postgresql.JSONB(), nullable=True))
    op.add_column("workflow_approvals", sa.Column("choice", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_approvals", "choice")
    op.drop_column("workflow_approvals", "choices")
