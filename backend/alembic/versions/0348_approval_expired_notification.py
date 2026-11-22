"""Notifications: a run's approval expired undecided, told to its owner (#move2).

An approval nobody decides ends its run as `cancelled` at the hourly sweep,
and a web-console user hears nothing about it - the run row just reads
`cancelled`. The sweep now writes an `approval_expired` notification to the
person who started the run, with the reason and the run to retry it from, so
the new event type has to be admitted by both CHECK constraints that hold
every notification row to the event vocabulary.

Revision ID: 0348_approval_expired_notification
Revises: 0347_network_connections
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0348_approval_expired_notification"
down_revision: str | None = "0347_network_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'improvement_finished', "
    "'eval_suite_reevaluated', 'eval_run_finished', 'case_generation_finished', "
    "'workflow_log_alert'"
)
_WITH_EXPIRED = f"{_EVENT_TYPE_VALUES}, 'approval_expired'"

_EVENT_TYPE_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _EVENT_TYPE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    _event_types(_WITH_EXPIRED)


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'approval_expired'")
    op.execute("DELETE FROM notifications WHERE event_type = 'approval_expired'")
    _event_types(_EVENT_TYPE_VALUES)
