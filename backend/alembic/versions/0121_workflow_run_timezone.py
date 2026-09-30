"""A run keeps its workflow's timezone: `workflow_runs.timezone`.

Taken from the workflow's settings when the run is admitted, as its deadline
is, so a date step that names no timezone writes in the workflow's, the same
for the whole run however the settings change meanwhile. Every existing run
reads as UTC, which is what its date steps used.

Revision ID: 0121_workflow_run_timezone
Revises: 0120_workflow_webhook_response
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0121_workflow_run_timezone"
down_revision: str | Sequence[str] | None = "0120_workflow_webhook_response"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "timezone")
