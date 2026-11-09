"""Retain activation and incident clocks without inventing historical attempts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0266_routine_activation_clock"
down_revision: str | None = "0265_trigger_delivery_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outcomes", sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "outcomes", sa.Column("last_recovered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("routine_activation_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("outcomes", "last_recovered_at")
    op.drop_column("outcomes", "last_observed_at")
    op.drop_column("agent_runs", "routine_activation_at")
