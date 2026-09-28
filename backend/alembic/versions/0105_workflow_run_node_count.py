"""Persist a workflow run's graph node count for the admission quota (#1907).

The admission quota bounds the queued and running node work an organization,
and a caller within it, may hold at once. It cannot read that from `node_runs`
alone: a run's node rows are created lazily as the graph fans out, so a run
that was just admitted shows only its single entry node, and many wide graphs
could be admitted before their work materialized. Stamping the run's whole node
count here, and summing it over the organization's live runs, makes the
reservation durable - counted the moment a run is admitted and released the
moment it reaches a terminal status. The sum reads the existing
`ix_workflow_run_org_status` index, so no new index is needed.

Added `NOT NULL` with a temporary `0` default to backfill any existing rows,
then the default is dropped: the service always stamps a real count.

Revision ID: 0105_workflow_run_node_count
Revises: 0104_workflow_runs
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0105_workflow_run_node_count"
down_revision: str | Sequence[str] | None = "0104_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("workflow_runs", "node_count", server_default=None)


def downgrade() -> None:
    op.drop_column("workflow_runs", "node_count")
