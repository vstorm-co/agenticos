"""Allow chat retries only after confirmed non-acceptance, fenced at each claim."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0273_notification_safe_retries"
down_revision: str | None = "0272_routine_device_waits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_deliveries",
        sa.Column("retry_safe", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_check_constraint(
        "ck_notification_retry_safe",
        "notification_deliveries",
        "NOT retry_safe OR (status = 'pending' AND claimed_at IS NULL AND claimed_until IS NOT NULL)",
    )


def downgrade() -> None:
    # Old workers retain their one-attempt chat contract. Pending safe refusals
    # become non-retryable; an accepted/uncertain submission is never replayed.
    op.drop_constraint("ck_notification_retry_safe", "notification_deliveries", type_="check")
    op.drop_column("notification_deliveries", "retry_safe")
