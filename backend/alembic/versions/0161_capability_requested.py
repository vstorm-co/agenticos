"""Notifications: somebody asked for a capability an agent lacks (#2301).

An agent told it cannot do something - search the web, read a knowledge base -
now says so with a card, and a person who may not change the agent asks its
owner from it. The owner is told through the notification centre, as a new
event type both CHECK constraints have to admit.

Revision ID: 0161_capability_requested
Revises: 0160_user_profile
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0161_capability_requested"
down_revision: str | None = "0160_user_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused'"
)
_WITH_REQUESTS = f"{_EVENT_TYPE_VALUES}, 'capability_requested'"

_EVENT_TYPE_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _EVENT_TYPE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    _event_types(_WITH_REQUESTS)


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'capability_requested'")
    op.execute("DELETE FROM notifications WHERE event_type = 'capability_requested'")
    _event_types(_EVENT_TYPE_VALUES)
