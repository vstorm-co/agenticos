"""Eval runs remember the proposal a check of the authoring assistant measured.

`eval_runs.proposal_check` holds what was checked - suggestions to an agent's
draft, or a proposed skill or context file body - with the version the change
was measured on and how many suggestions it carried. A run that holds it is
hypothetical: nothing is accepted by checking, so its answers are not sent to
a dataset's review queue unless a person sends them.

Every existing run was started some other way or reads well enough as one, so
nothing is backfilled. The downgrade drops the column.

Revision ID: 0178_eval_run_proposal_check
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0178_eval_run_proposal_check"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("proposal_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "proposal_check")
