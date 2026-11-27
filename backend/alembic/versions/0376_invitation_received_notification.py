"""An invitation to an organization reaches its recipient as a notification.

A signed-in invitee who follows an invitation deep link lands on an accept
request that errors whenever the invitation cannot be accepted for their
account - a different address, an expired invitation, a seat limit - and the
page has nothing to offer them but the error. The invitation is now a
notification row as well, written when it is created for an existing account,
so it shows up in their inbox and links them to where they can join.

Revision ID: 0376_invitation_received_notification
Revises: 0375_merge_t3_v1950
Create Date: 2026-11-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0376_invitation_received_notification"
down_revision: str | None = "0375_merge_t3_v1950"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'approval_expired', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'workflow_notification', "
    "'artifact_owner_changed', 'artifact_share_requested', "
    "'capability_requested', 'suggestion', 'finding', 'improvement_finished', "
    "'eval_suite_reevaluated', 'eval_run_finished', 'case_generation_finished', "
    "'workflow_log_alert', 'room_mention', 'room_thread_reply'"
)
_WITH_INVITATION = f"{_EVENT_TYPE_VALUES}, 'invitation_received'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    _event_types(_WITH_INVITATION)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'invitation_received'")
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'invitation_received'")
    _event_types(_EVENT_TYPE_VALUES)
