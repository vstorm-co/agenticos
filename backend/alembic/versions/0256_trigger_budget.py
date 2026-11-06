"""A routine's own monthly budget (#2575).

Revision ID: 0256_trigger_budget
Revises: 0255_trigger_delivery
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0256_trigger_budget"
down_revision: str | None = "0255_trigger_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers", sa.Column("monthly_budget_usd", sa.Numeric(12, 4), nullable=True)
    )
    op.create_check_constraint(
        "ck_trigger_budget",
        "agent_triggers",
        "monthly_budget_usd IS NULL OR monthly_budget_usd > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trigger_budget", "agent_triggers", type_="check")
    op.drop_column("agent_triggers", "monthly_budget_usd")
