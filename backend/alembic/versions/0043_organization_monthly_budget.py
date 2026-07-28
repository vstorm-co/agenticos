"""The ceiling on what an organization's agents may spend in a month

Revision ID: 0043_org_monthly_budget
Revises: 0042_exposure_budget
Create Date: 2026-07-27

Until now the only spending limit that bound anything was ``AgentSpec.budget``,
set per agent in the Builder. An organization with twelve agents therefore had
twelve independent caps and no ceiling: each one could be right and the bill
still twelve times what anybody signed off. On a platform billed per token that
is the control an operator most expects to exist.

Nullable, and deliberately so. The cap is opt-in - a default number nobody chose
would stop somebody's agents on a date they did not pick - and ``NULL`` reads as
"no organization-wide ceiling", which is what every existing row means today.

``Numeric(12, 6)`` matches ``agent_runs.cost_usd``, because that is what the cap
is measured against: the same month-to-date sum the Activity page shows. A cap
stored at a different scale would round differently from the total it is
compared with, and the two numbers would disagree in the one place it matters.
"""

import sqlalchemy as sa

from alembic import op

revision = "0043_org_monthly_budget"
down_revision = "0042_exposure_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("monthly_budget_usd", sa.Numeric(12, 6), nullable=True)
    )
    # A cap of zero is not a tighter cap, it is an organization whose agents can
    # never answer - and it is one keystroke away from the number somebody meant
    # to type. The same guard is on ``agent_exposures``.
    op.create_check_constraint(
        "ck_organization_budget_positive",
        "organizations",
        "monthly_budget_usd IS NULL OR monthly_budget_usd > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_organization_budget_positive", "organizations", type_="check")
    op.drop_column("organizations", "monthly_budget_usd")
