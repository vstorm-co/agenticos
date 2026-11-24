"""Bound improvement loops and record why they stopped.

Revision ID: 0197_improvement_rounds
Revises: 0196_improvement_holdout
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0197_improvement_rounds"
down_revision: str | None = "0196_improvement_holdout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', 'permission', 'stale', 'stalled', 'proposal', 'eval', 'superseded', 'knowledge_only', 'draft'"


def _check(values: str) -> None:
    op.drop_constraint("ck_improvement_run_stop_reason", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_stop_reason",
        "improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({values})",
    )


def upgrade() -> None:
    op.add_column(
        "improvement_iterations",
        sa.Column(
            "attribution_eval_run_ids", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
    )
    _check(_OLD + ", 'max_iterations', 'repeat_candidate'")


def downgrade() -> None:
    op.drop_column("improvement_iterations", "attribution_eval_run_ids")
    op.execute(
        "UPDATE improvement_runs SET stop_reason = 'no_change' WHERE stop_reason IN ('max_iterations', 'repeat_candidate')"
    )
    _check(_OLD)
