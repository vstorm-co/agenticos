"""Allow shop_live_agent_queued notification event type (D3 B52).

Revision ID: 0108_shop_live_agent_queued_notification
Revises: 0107_shop_widget_handling
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0108_shop_live_agent_queued_notification"
down_revision: str | None = "0107_shop_widget_handling"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'shop_live_agent_queued'"
)


def upgrade() -> None:
    op.drop_constraint("ck_notifications_event_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_event_type",
        "notifications",
        f"event_type IN ({_EVENT_TYPE_VALUES})",
    )
    op.drop_constraint(
        "ck_notification_preferences_event_type", "notification_preferences", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_preferences_event_type",
        "notification_preferences",
        f"event_type IN ({_EVENT_TYPE_VALUES})",
    )


def downgrade() -> None:
    _LEGACY = (
        "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
        "'ingestion_completed', 'ingestion_failed', 'usage_report', "
        "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement'"
    )
    op.drop_constraint("ck_notifications_event_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notifications_event_type",
        "notifications",
        f"event_type IN ({_LEGACY})",
    )
    op.drop_constraint(
        "ck_notification_preferences_event_type", "notification_preferences", type_="check"
    )
    op.create_check_constraint(
        "ck_notification_preferences_event_type",
        "notification_preferences",
        f"event_type IN ({_LEGACY})",
    )
