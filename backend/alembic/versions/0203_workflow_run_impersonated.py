"""Remember that a workflow run started under impersonation.

`workflow_runs.impersonated` is true for a run an administrator started while
impersonating its principal, and for every run in the chain such a run causes. The
request that knew is gone by the time a worker runs a node, so the run carries it:
an agent step under it may not do what impersonation refuses (consenting to a page's
data automatically). Existing runs read false, which is what they were.

Revision ID: 0203_workflow_run_impersonated
Revises: 0202_artifact_actions
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0203_workflow_run_impersonated"
down_revision: str | Sequence[str] | None = "0202_artifact_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("impersonated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "impersonated")
