"""A run another workflow's step called, and the step waiting on it.

`workflow_runs.parent_node_run_id` names the `workflow.run` step whose run this
one is: when it ends, the step is woken and hands on its output or its error.
Null for every existing run, and cleared, not cascaded, when the calling run is
removed. `workflow_runs.triggered_by` gains `workflow_call`. The downgrade drops
the column and narrows the check back, which fails while such a run exists.

Revision ID: 0118_workflow_calls
Revises: 0117_workflow_settings
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0118_workflow_calls"
down_revision: str | Sequence[str] | None = "0117_workflow_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_BEFORE = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'workflow_failed')"
)
_AFTER = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'workflow_failed', 'workflow_call')"
)


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("parent_node_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "workflow_runs_parent_node_run_id_fkey",
        "workflow_runs",
        "node_runs",
        ["parent_node_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("workflow_runs_parent_node_run_id_idx", "workflow_runs", ["parent_node_run_id"])
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _AFTER)


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "workflow_runs", _BEFORE)
    op.drop_index("workflow_runs_parent_node_run_id_idx", table_name="workflow_runs")
    op.drop_constraint("workflow_runs_parent_node_run_id_fkey", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "parent_node_run_id")
