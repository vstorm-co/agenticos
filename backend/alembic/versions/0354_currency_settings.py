"""Add deployment currency settings and nullable organization overrides.

Existing deployment and organization rows inherit USD unless the operator
explicitly configures another default. Model prices and monetary limits are not
rewritten; missing pricing currencies in pre-existing JSON continue to mean USD.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0354_currency_settings"
down_revision: str = "0353_monetary_cost_capacity"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column("currency_settings", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("currency", sa.String(3), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "currency")
    op.drop_column("deployment_settings", "currency_settings")
