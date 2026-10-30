"""Budget reservations and a stored late result on a step's attempts.

`node_attempts.reserved_usd` is what an attempt of a model or knowledge step was
handed to spend when it began, so two parallel steps under one workflow budget cannot
both be given the whole remainder. It is read only while the attempt is `in_flight`:
settling, parking or being resolved as uncertain ends the hold, so nothing has to be
released and no counter can drift. `NULL` means the attempt reserved nothing (a run
without a budget, a step that spends none). A step that calls a workflow reserves
like any spender when it begins, and the hold moves to the called run's own budget.

`node_attempts.late_result` keeps the result an attempt reported after it had been
resolved as `uncertain`, so a person can still use it. It is written once, by the
settle that finds the attempt already resolved, and never changes the attempt's
verdict, so the table stays append-only in what it decided. `NULL` means none arrived.

Both columns are nullable and read by no old code; the downgrade drops them.

Revision ID: 0241_attempt_reservations
Revises: 0240_workflow_log_alerts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0241_attempt_reservations"
down_revision: str | Sequence[str] | None = "0240_workflow_log_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "node_attempts", sa.Column("reserved_usd", sa.Numeric(precision=12, scale=6), nullable=True)
    )
    op.add_column("node_attempts", sa.Column("late_result", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_node_attempt_reserved",
        "node_attempts",
        "reserved_usd IS NULL OR reserved_usd >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_node_attempt_reserved", "node_attempts", type_="check")
    op.drop_column("node_attempts", "late_result")
    op.drop_column("node_attempts", "reserved_usd")
