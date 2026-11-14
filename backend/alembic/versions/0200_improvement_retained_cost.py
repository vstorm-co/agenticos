"""Preserve session spend when activity retention removes its paid root runs.

Revision ID: 0200_improvement_retained_cost
Revises: 0199_create_skill_proposals
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0200_improvement_retained_cost"
down_revision: str | None = "0199_create_skill_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column("archived_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_improvement_run_archived_cost", "improvement_runs", "archived_cost_usd >= 0"
    )
    # Keep any already-recorded spend whose underlying activity has gone.
    op.execute("""UPDATE improvement_runs AS session SET archived_cost_usd = GREATEST(
        session.spent_usd - COALESCE((SELECT SUM(run.cost_usd) FROM agent_runs AS run
            WHERE run.improvement_run_id = session.id AND run.organization_id = session.organization_id
                AND run.parent_run_id IS NULL), 0), 0)""")


def downgrade() -> None:
    op.drop_constraint("ck_improvement_run_archived_cost", "improvement_runs", type_="check")
    op.drop_column("improvement_runs", "archived_cost_usd")
