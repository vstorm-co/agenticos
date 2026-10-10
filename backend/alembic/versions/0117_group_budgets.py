"""A department's monthly budget, and the warning at 80% of it (#2072).

Revision ID: 0117_group_budgets
Revises: 0116_group_leads_and_shares
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0117_group_budgets"
down_revision: str | None = "0116_group_leads_and_shares"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared'"
)
_WITH_WARNING = f"{_EVENT_TYPE_VALUES}, 'budget_warning'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column("groups", sa.Column("monthly_budget_usd", sa.Numeric(12, 6), nullable=True))
    op.create_check_constraint(
        op.f("groups_ck_group_budget_positive_check"),
        "groups",
        "monthly_budget_usd IS NULL OR monthly_budget_usd > 0",
    )
    _event_types(_WITH_WARNING)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'budget_warning'")
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'budget_warning'")
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_constraint(op.f("groups_ck_group_budget_positive_check"), "groups", type_="check")
    op.drop_column("groups", "monthly_budget_usd")
