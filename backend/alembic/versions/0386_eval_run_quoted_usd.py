"""An eval run keeps the price it was started at, so its worker can hold it there.

A person accepts a run at a price, an eval suite caps what one of its runs may
cost, and a skill check is accepted at its most. Each was compared with the
estimate once, before the run started; the run now keeps that price and its
worker starts no work that would take it past it.

Runs started before this migration keep no price and run as they did.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0386_eval_run_quoted_usd"
down_revision: str = "0385_shared_onboarding_scopes"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("quoted_usd", sa.Numeric(38, 6), nullable=True))

    op.add_column(
        "eval_runs",
        sa.Column("grading_estimate_usd", sa.Numeric(38, 6), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "grading_estimate_usd")
    op.drop_column("eval_runs", "quoted_usd")
