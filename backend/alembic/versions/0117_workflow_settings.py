"""A workflow's own settings, a schedule's timezone, and runs a failure starts.

`workflows.settings` holds what a workflow is run with rather than what it does:
the timezone its schedules keep, the deadline a run gets when nobody names one,
the workflow started when a run fails, and how long its runs are kept. It is
the workflow's, not a version's - changing it changes every later run - and
starts empty, which means UTC, no deadline, no error workflow, runs kept.

`workflow_exposures.timezone` is the schedule's copy of that timezone, set when
it is published and when the setting changes, so the heartbeat that claims due
schedules computes each next tick without reading every workflow. Existing
schedules keep UTC.

`workflow_runs.triggered_by` gains `workflow_failed`, for a run an error
workflow is started with. The downgrade drops the columns and narrows the check
back, which fails while such a run exists.

Revision ID: 0117_workflow_settings
Revises: 0116_workflow_run_retry
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0117_workflow_settings"
down_revision: str | Sequence[str] | None = "0116_workflow_run_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_BEFORE = "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created')"
_AFTER = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'workflow_failed')"
)


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column(
        "workflow_exposures",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
    )
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _BEFORE)
    op.drop_column("workflow_exposures", "timezone")
    op.drop_column("workflows", "settings")
