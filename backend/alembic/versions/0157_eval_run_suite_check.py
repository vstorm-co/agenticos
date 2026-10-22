"""Eval runs remember the suite a check of authoring suggestions was made on.

`eval_runs.suite_check` holds the suite's id, name and threshold as they stood
when the check started, so the run's read can say what the suite would have
said of it. It is not a foreign key: the snapshot outlives the suite, and no
suite result points at a check.

Every existing run was started some other way, so nothing is backfilled. The
downgrade drops the column, and a check's run reads as any other gate run.

Revision ID: 0157_eval_run_suite_check
Revises: 0156_authoring_agent_parts
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0157_eval_run_suite_check"
down_revision: str | None = "0156_authoring_agent_parts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("suite_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "suite_check")
