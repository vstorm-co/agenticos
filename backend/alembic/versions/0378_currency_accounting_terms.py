"""Freeze reporting quotes and retain configured monetary limit terms.

Existing scalar API amounts remain accounting USD. The baseline quote is USD/1;
startup reconciles an explicitly configured inherited default currency once,
without repricing existing receipts or limits. No original term is inferred as
non-USD from a display preference. Rate-only edits never refresh display quotes.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0378_currency_accounting_terms"
down_revision = "0377_currency_settings"
branch_labels = None
depends_on = None

_FIELDS = {
    "organizations": ("monthly_budget_usd", "proactive_limit_usd"),
    "groups": ("monthly_budget_usd",),
    "agent_triggers": ("monthly_budget_usd",),
    "eval_suites": ("max_run_usd",),
    "improvement_runs": ("budget_usd",),
    "skill_improvement_runs": ("budget_usd",),
    "system_agent_profiles": ("monthly_budget_usd",),
    "phone_endpoints": ("daily_budget_usd", "price_per_minute_usd"),
}


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "reporting_quote",
            JSONB,
            nullable=False,
            server_default=sa.text('\'{"currency":"USD","units_per_usd":"1"}\''),
        ),
    )
    op.execute(
        "UPDATE organizations AS org SET reporting_quote = jsonb_build_object("
        "'currency', org.currency, 'units_per_usd', "
        "(SELECT currency_settings->'rates'->org.currency FROM deployment_settings LIMIT 1)) "
        "WHERE org.currency IS NOT NULL AND org.currency != 'USD'"
    )
    for table, fields in _FIELDS.items():
        op.add_column(
            table,
            sa.Column("monetary_terms", JSONB, nullable=False, server_default=sa.text("'{}'")),
        )
        for field in fields:
            op.execute(
                f"UPDATE {table} SET monetary_terms = monetary_terms || jsonb_build_object('{field}', "
                f"jsonb_build_object('amount', {field}::text, 'currency', 'USD', 'units_per_usd', '1', 'cost_usd', {field}::text)) "
                f"WHERE {field} IS NOT NULL"
            )


def downgrade() -> None:
    for table in reversed(_FIELDS):
        foreign = op.get_bind().scalar(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM {table}, jsonb_each(monetary_terms) AS term WHERE term.value->>'currency' != 'USD')"
            )
        )
        if foreign:
            raise RuntimeError(
                "Cannot discard original non-USD limit terms; explicitly reconfigure them in USD before downgrading"
            )
    for table in reversed(_FIELDS):
        op.drop_column(table, "monetary_terms")
    op.drop_column("organizations", "reporting_quote")
