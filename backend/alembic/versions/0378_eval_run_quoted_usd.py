"""An eval run keeps the price it was started at, so its worker can hold it there.

A person accepts a run at a price, an eval suite caps what one of its runs may
cost, and a skill check is accepted at its most. Each was compared with the
estimate once, before the run started; the run now keeps that price and its
worker starts no work that would take it past it. The run also keeps what the
estimate priced one answer of each side and one grading at, which the worker
reserves for the work it has under way.

Runs started before this migration keep no price and run as they did.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0378_eval_run_quoted_usd"
down_revision: str | None = "0375_tool_approval_platform_call"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("quoted_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("eval_runs", sa.Column("grade_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("eval_run_arms", sa.Column("answer_usd", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_run_arms", "answer_usd")
    op.drop_column("eval_runs", "grade_usd")
    op.drop_column("eval_runs", "quoted_usd")
