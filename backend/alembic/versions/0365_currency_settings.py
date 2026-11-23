"""Add deployment currency settings and nullable organization overrides.

Existing deployment and organization rows inherit USD unless the operator
explicitly configures another default. Model prices and monetary limits are not
rewritten; missing pricing currencies in pre-existing JSON continue to mean USD.
Downgrade removes explicit USD tags and refuses prices in other currencies.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0365_currency_settings"
down_revision: str = "0364_monetary_cost_capacity"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column("currency_settings", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("currency", sa.String(3), nullable=True))


def downgrade() -> None:
    op.execute("LOCK TABLE model_profiles IN SHARE ROW EXCLUSIVE MODE")
    non_usd = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM model_profiles WHERE custom_pricing ? 'currency' "
            "AND custom_pricing->>'currency' IS DISTINCT FROM 'USD')"
        )
    )
    if non_usd:
        raise RuntimeError(
            "Set non-USD custom model prices to automatic pricing or explicitly reprice them in USD before downgrading"
        )
    op.execute(
        "UPDATE model_profiles SET custom_pricing = custom_pricing - 'currency' WHERE custom_pricing ? 'currency'"
    )
    op.drop_column("organizations", "currency")
    op.drop_column("deployment_settings", "currency_settings")
