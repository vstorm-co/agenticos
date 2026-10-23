"""A workflow run an agent's `run_workflow` tool starts.

`workflow_runs.triggered_by` gains `agent`. The downgrade narrows it back, which
fails while such a run exists.

Revision ID: 0184_workflow_run_from_agent
Revises: 0183_table_trigger_events
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0184_workflow_run_from_agent"
down_revision: str | None = "0183_table_trigger_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_BEFORE = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call')"
)
_AFTER = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _BEFORE)
