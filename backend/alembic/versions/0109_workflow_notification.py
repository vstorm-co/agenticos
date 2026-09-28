"""Let a workflow's notification step write to the notification center (#1789).

`notification.send` addresses members the workflow chose, not the audience of an
agent's alert setting, so it is an event type of its own: `workflow_notification`.
The vocabulary is held to by a CHECK on `notifications.event_type` and one on
`notification_preferences.event_type` (so a person can turn it off per channel);
both are recreated with the new value.

The downgrade deletes rows of the new type before restoring the narrower CHECKs,
which a remaining row would otherwise violate.

Revision ID: 0109_workflow_notification
Revises: 0108_workflow_run_io
Create Date: 2026-09-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0109_workflow_notification"
down_revision: str | Sequence[str] | None = "0108_workflow_run_io"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement'"
)
_AFTER = f"{_BEFORE}, 'workflow_notification'"

_CHECKS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _recreate(values: str) -> None:
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    _recreate(_AFTER)


def downgrade() -> None:
    for table, _name in _CHECKS:
        op.execute(f"DELETE FROM {table} WHERE event_type = 'workflow_notification'")
    _recreate(_BEFORE)
