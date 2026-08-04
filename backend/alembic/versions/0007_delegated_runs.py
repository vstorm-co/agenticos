"""A run that was delegated from another run

Revision ID: 0007_delegated_runs
Revises: 0006_message_usage
Create Date: 2026-08-04

A delegation to a published agent gets an `agent_runs` row of its own, so that
"what has the researcher agent cost this month" has an answer and its own
monthly cap has something to meter. Two columns make that row readable.

`parent_run_id` says which run delegated it. It is also what keeps the
organization's monthly total honest: every run shares one spend ledger, so the
parent's row already contains the delegation's tokens, and summing both would
bill the organization twice for one request. `sum_cost_since` therefore counts
only rows where this is null, while the per-agent sum counts all of them - the
delegate's own spend is exactly what its own cap is a cap on.

`ON DELETE SET NULL` for the same arithmetic. Deleting the parent removes the
row that contained this cost, so a delegation row that becomes top-level is one
that *should* start counting; cascading would delete the record of money that
was spent.

`subagent_task_id` is the delegation library's own task id, eight hex characters
today. It is what joins this row to the handle the parent's model saw, so
`check_task('4f2a1b8c')` in a transcript and this row are the same delegation
rather than two things that look related. `String(32)` leaves room for the
library to lengthen it without another migration.

No new `RunSurface` member. A Slack mention that delegated is still Slack, and
one column cannot answer both "where did this come from" and "was this
delegated".

The index is for the run-detail question - "what did this run delegate" - which
is a lookup by parent. The monthly sums are still served by the existing
`(organization_id, started_at)` index, with the null test applied to rows it
already found.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007_delegated_runs"
down_revision = "0006_message_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("agent_runs", sa.Column("subagent_task_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        op.f("agent_runs_parent_run_id_fkey"),
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("agent_runs_parent_run_id_idx"), "agent_runs", ["parent_run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("agent_runs_parent_run_id_idx"), table_name="agent_runs")
    op.drop_constraint(op.f("agent_runs_parent_run_id_fkey"), "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "subagent_task_id")
    op.drop_column("agent_runs", "parent_run_id")
