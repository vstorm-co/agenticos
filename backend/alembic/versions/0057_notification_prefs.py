"""Per-user notification preferences

Revision ID: 0057_notification_prefs
Revises: 0056_skill_category
Create Date: 2026-07-28

The three lifecycle emails (budget exceeded, approval requested, usage report)
each get an opt-out on the user, consulted where recipients are resolved in
NotificationService. Server default true: every existing user has been
receiving these emails, and a migration must not silently unsubscribe them.

Trimmed from autogenerate output: the comparison also proposed renaming dozens
of template-era indexes to the current naming convention, which is not this
change and belongs to no change until it is made deliberately.
"""

import sqlalchemy as sa

from alembic import op

revision = "0057_notification_prefs"
down_revision = "0056_skill_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "notify_budget_alerts", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_approval_requests",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_usage_reports", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_usage_reports")
    op.drop_column("users", "notify_approval_requests")
    op.drop_column("users", "notify_budget_alerts")
