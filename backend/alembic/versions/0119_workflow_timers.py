"""A step that waits on a clock: `timer` as a reason to be parked.

A Wait step parks its node run until a moment - a duration after it was reached,
or a time it was given - and its dispatch row comes due then, so the wait
survives a worker restart. `node_runs.waiting_reason` and
`workflow_runs.paused_reason` gain `timer`. The downgrade narrows both checks
back, which fails while a step waits on one.

Revision ID: 0119_workflow_timers
Revises: 0118_workflow_calls
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0119_workflow_timers"
down_revision: str | Sequence[str] | None = "0118_workflow_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "('approval', 'external_event', 'retry_backoff')"
_AFTER = "('approval', 'external_event', 'retry_backoff', 'timer')"
_CHECKS = (
    ("workflow_runs", "workflow_runs_ck_workflow_run_paused_reason_check", "paused_reason"),
    ("node_runs", "node_runs_ck_node_run_waiting_reason_check", "waiting_reason"),
)


def _replace(reasons: str) -> None:
    for table, name, column in _CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"{column} IS NULL OR {column} IN {reasons}")


def upgrade() -> None:
    _replace(_AFTER)


def downgrade() -> None:
    _replace(_BEFORE)
