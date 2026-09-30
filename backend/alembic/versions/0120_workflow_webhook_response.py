"""A webhook answered from the graph: `workflow_runs.webhook_response`.

A Respond to webhook step names the status, headers and body the delivery that
started its run is answered with, and the first one to complete writes them
here - the door waiting on the run reads this column. Nullable, so every
existing run reads as one that never answered.

Revision ID: 0120_workflow_webhook_response
Revises: 0119_workflow_timers
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0120_workflow_webhook_response"
down_revision: str | Sequence[str] | None = "0119_workflow_timers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("webhook_response", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "webhook_response")
