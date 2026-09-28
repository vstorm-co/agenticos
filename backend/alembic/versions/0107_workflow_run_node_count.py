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

Added `NOT NULL` with a temporary `0` default, then existing rows are backfilled
with their real graph node count - from the published version's graph for a real
run, from the frozen snapshot for a test run - so a run already in flight when
this lands still holds its reservation rather than reading as zero work.

The `0` server default is kept, not dropped: this is the expand half of an
expand/contract change, so a writer that does not yet know the column (a
not-yet-upgraded instance during a rolling deploy) can still insert a row without
violating `NOT NULL`. The service always stamps a real count; a later change may
drop the default once every writer supplies one.

Revision ID: 0107_workflow_run_node_count
Revises: 0106_workflow_runs
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0107_workflow_run_node_count"
down_revision: str | Sequence[str] | None = "0106_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Backfill real graph sizes. The run's graph source is exactly one of these
    # (a CHECK guarantees it), so the two updates are disjoint. `jsonb_array_length`
    # of a missing or non-array `nodes` is coalesced to 0.
    op.execute(
        """
        UPDATE workflow_runs AS r
        SET node_count = COALESCE(jsonb_array_length(v.graph -> 'nodes'), 0)
        FROM workflow_versions AS v
        WHERE r.workflow_version_id = v.id
        """
    )
    op.execute(
        """
        UPDATE workflow_runs
        SET node_count = COALESCE(jsonb_array_length(draft_graph_snapshot -> 'nodes'), 0)
        WHERE draft_graph_snapshot IS NOT NULL
        """
    )
    # The server default is intentionally left in place (expand/contract).


def downgrade() -> None:
    op.drop_column("workflow_runs", "node_count")
