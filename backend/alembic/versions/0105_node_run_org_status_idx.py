"""The index the workflow admission quota reads on every start (#1907).

Admitting a run counts an organization's queued and running node runs - and,
for the caller, joins `workflow_runs` for the principal - to refuse a start
that would push outstanding node work past its ceiling. `node_runs` had
`organization_id` and `status` indexed only separately, so that count fanned
out over every node run the organization ever had, terminal ones included.
This composite mirrors `ix_workflow_run_org_status`, which answers the same
question for runs.

Revision ID: 0105_node_run_org_status_idx
Revises: 0104_workflow_runs
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0105_node_run_org_status_idx"
down_revision: str | Sequence[str] | None = "0104_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_node_run_org_status"


def upgrade() -> None:
    op.create_index(_INDEX, "node_runs", ["organization_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="node_runs")
