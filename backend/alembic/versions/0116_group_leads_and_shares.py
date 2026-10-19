"""A group's lead, and members told when something is shared with their group (#2072).

Revision ID: 0116_group_leads_and_shares
Revises: 0115_channel_bot_touches
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0116_group_leads_and_shares"
down_revision: str | None = "0115_channel_bot_touches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published'"
)
_WITH_SHARES = f"{_EVENT_TYPE_VALUES}, 'resource_shared'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column(
        "group_members",
        sa.Column("is_lead", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _event_types(_WITH_SHARES)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'resource_shared'")
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'resource_shared'")
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_column("group_members", "is_lead")
