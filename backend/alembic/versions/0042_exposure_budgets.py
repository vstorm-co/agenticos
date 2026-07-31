"""Spend attributable to an exposure, and the caps that bound it

Revision ID: 0042_exposure_budget
Revises: 0041_message_agent
Create Date: 2026-07-27

An exposure is where an agent is available, and each one needs its own ceiling.
That requires two things the schema did not have.

`agent_runs.exposure_id` is the attribution. Without it "what has this Slack
binding spent this month" is not a question the database can answer, and a cap
on an exposure would have to be measured against the organization's total -
which is not a cap on the exposure at all, since unrelated internal runs would
exhaust it and the exposure's own traffic would never be visible in it.

`agent_exposures.max_per_run_usd` and `monthly_usd` are the ceilings. Both
are nullable and both are meaningful today: capping what a Slack binding can
spend is worth having on its own. They become mandatory for a surface open to
anonymous visitors, where a budget is the only thing between a public URL and
somebody's card - but that constraint arrives with that surface, so it can be
written against rows the schema will actually accept.

Two limits rather than one because they fail differently. A monthly cap stops a
slow leak; only a per-run cap stops a single adversarial prompt driving a loop,
and a rate limiter cannot see cost.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0042_exposure_budget"
down_revision = "0041_message_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SET NULL rather than CASCADE: deleting a binding must not delete the
    # history of what it spent. A run whose exposure is gone still happened, and
    # still cost money somebody is accounting for.
    op.add_column(
        "agent_runs",
        sa.Column(
            "exposure_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("agent_exposures.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # The index the monthly lookup runs on, in the shape it queries: one
    # exposure, one window. Without it the check that happens before every model
    # request scans the organization's runs.
    op.create_index(
        "ix_agent_runs_exposure_started",
        "agent_runs",
        ["exposure_id", "started_at"],
    )

    op.add_column("agent_exposures", sa.Column("max_per_run_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("agent_exposures", sa.Column("monthly_usd", sa.Numeric(12, 6), nullable=True))
    # A limit of zero or less is not a tighter limit, it is a binding that can
    # never answer - which somebody would eventually reach by clearing a field.
    op.create_check_constraint(
        "ck_exposure_budget_positive",
        "agent_exposures",
        "(max_per_run_usd IS NULL OR max_per_run_usd > 0) "
        "AND (monthly_usd IS NULL OR monthly_usd > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_exposure_budget_positive", "agent_exposures", type_="check")
    op.drop_column("agent_exposures", "monthly_usd")
    op.drop_column("agent_exposures", "max_per_run_usd")
    op.drop_index("ix_agent_runs_exposure_started", table_name="agent_runs")
    op.drop_column("agent_runs", "exposure_id")
