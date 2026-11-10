"""Keep human-selected changes and earlier measurements without dismissing proposals.

Revision ID: 0204_improvement_selection
Revises: 0203_eval_completion_notices
The nullable selection preserves old full-proposal rounds. Earlier combined
and attribution check IDs remain readable after a selected recheck, while the
active measurement has its own confirming-repeat limit.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0204_improvement_selection"
down_revision: str | None = "0203_eval_completion_notices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_iterations",
        sa.Column("included_hunk_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
    )
    op.add_column(
        "improvement_iterations",
        sa.Column(
            "previous_eval_run_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("improvement_iterations", "previous_eval_run_ids")
    op.drop_column("improvement_iterations", "included_hunk_ids")
