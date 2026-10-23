"""The workflows a page may start (#1976).

`artifact_versions.actions` holds what a version declares: `[{workflow_id, label}]`,
immutable with the version. `workflow_runs` gains `source_artifact_id` (the page a run
started from; SET NULL, so deleting a page keeps its runs) and `source_version_number`,
and `triggered_by` gains `app`. The downgrade turns the `app` runs into `api` runs
before it narrows the CHECK - they were started by a member, as an API run is.

Revision ID: 0202_artifact_actions
Revises: 0201_artifact_public_data
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0202_artifact_actions"
down_revision: str | Sequence[str] | None = "0201_artifact_public_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_CHECK = "workflow_runs_ck_workflow_run_triggered_by_check"
_RUNS = (
    "triggered_by IN ('api', 'websocket', 'webhook', 'chat', 'schedule', 'table_created', "
    "'table_updated', 'table_deleted', 'workflow_failed', 'workflow_call', 'agent', 'form', "
    "'channel_message', 'github', 'gmail'"
)
_INDEX = "workflow_runs_source_artifact_id_idx"


def upgrade() -> None:
    op.add_column(
        "artifact_versions",
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.add_column(
        "workflow_runs",
        sa.Column(
            "source_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("workflow_runs", sa.Column("source_version_number", sa.Integer(), nullable=True))
    op.create_index(op.f(_INDEX), "workflow_runs", ["source_artifact_id"])
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS}, 'app')")


def downgrade() -> None:
    op.drop_constraint(op.f(_RUN_CHECK), "workflow_runs", type_="check")
    op.execute("UPDATE workflow_runs SET triggered_by = 'api' WHERE triggered_by = 'app'")
    op.create_check_constraint(op.f(_RUN_CHECK), "workflow_runs", f"{_RUNS})")
    op.drop_index(op.f(_INDEX), table_name="workflow_runs")
    op.drop_column("workflow_runs", "source_version_number")
    op.drop_column("workflow_runs", "source_artifact_id")
    op.drop_column("artifact_versions", "actions")
