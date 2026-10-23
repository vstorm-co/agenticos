"""Whose failure a failed eval attempt was (#2359).

A failed attempt counted as neither passed nor failed, so an agent that crashed
on fourteen cases and passed one reported a pass rate of 100%. The worker now
records whose failure it was: the agent's counts against it, the
infrastructure's leaves the case incomplete. Attempts that failed before this
revision keep no fault and read as incomplete, since their error text cannot
say reliably which it was.

Revision ID: 0176_eval_case_fault
Revises: 0180_improvement_sessions
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0176_eval_case_fault"
down_revision: str | None = "0180_improvement_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "eval_run_cases_ck_eval_run_case_fault_check"


def upgrade() -> None:
    op.add_column("eval_run_cases", sa.Column("fault", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f(_CHECK), "eval_run_cases", "fault IN ('agent', 'infrastructure')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "eval_run_cases", type_="check")
    op.drop_column("eval_run_cases", "fault")
