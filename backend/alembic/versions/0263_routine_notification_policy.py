"""Narrow routine delivery channels and distinguish requested watch reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0263_routine_notification_policy"
down_revision: str | None = "0262_watch_agent_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("agent_triggers", "watches"):
        op.add_column(table, sa.Column("notification_channels", JSONB(), nullable=True))
    op.add_column(
        "watches", sa.Column("last_reported_activation", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "watches", sa.Column("report_mode", sa.String(16), nullable=False, server_default="changes")
    )
    op.create_check_constraint(
        "ck_watch_report_mode", "watches", "report_mode IN ('changes', 'every_check')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_watch_report_mode", "watches", type_="check")
    op.drop_column("watches", "report_mode")
    op.drop_column("watches", "last_reported_activation")
    for table in ("watches", "agent_triggers"):
        op.drop_column(table, "notification_channels")
