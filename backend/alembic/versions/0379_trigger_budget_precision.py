"""Preserve six-decimal routine budget declarations and reject lossy rollback."""

import sqlalchemy as sa

from alembic import op

revision = "0379_trigger_budget_precision"
down_revision = "0378_currency_accounting_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "agent_triggers",
        "monthly_budget_usd",
        existing_type=sa.Numeric(12, 4),
        type_=sa.Numeric(38, 6),
        existing_nullable=True,
    )


def downgrade() -> None:
    lossy = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_triggers WHERE "
            "monthly_budget_usd != trunc(monthly_budget_usd, 4) "
            "OR abs(monthly_budget_usd) >= 100000000)"
        )
    )
    if lossy:
        raise RuntimeError(
            "Routine budgets exceed the old four-decimal capacity; "
            "retain this migration or explicitly adjust those limits before downgrade"
        )
    op.alter_column(
        "agent_triggers",
        "monthly_budget_usd",
        existing_type=sa.Numeric(38, 6),
        type_=sa.Numeric(12, 4),
        existing_nullable=True,
    )
