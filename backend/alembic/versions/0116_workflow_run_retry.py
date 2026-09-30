"""A run that retries another: the steps that succeeded there are not run again.

`workflow_runs.retry_of_run_id` names the run a retry was started from. Each step
of the retry that succeeded in that run hands on the output it had there instead
of running again, so a step with a side effect is never repeated. Null for every
existing run. It is cleared, not cascaded, when the original run is removed: the
retry keeps its own history. The downgrade drops it.

Revision ID: 0116_workflow_run_retry
Revises: 0115_workflow_tags
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0116_workflow_run_retry"
down_revision: str | Sequence[str] | None = "0115_workflow_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("retry_of_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "workflow_runs_retry_of_run_id_fkey",
        "workflow_runs",
        "workflow_runs",
        ["retry_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("workflow_runs_retry_of_run_id_fkey", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "retry_of_run_id")
