"""Tell a page's old and new owner when its ownership changes (#1974).

Handing a page to another member, or an Owner or Admin reassigning one, is an event
of its own: `artifact_owner_changed`. The vocabulary is held to by a CHECK on
`notifications.event_type` and one on `notification_preferences.event_type` (so a
person can turn it off per channel); both are recreated with the new value.

The downgrade deletes rows of the new type before restoring the narrower CHECKs,
which a remaining row would otherwise violate.

Revision ID: 0216_artifact_owner_changed
Revises: 0215_artifact_consent
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0216_artifact_owner_changed"
down_revision: str | Sequence[str] | None = "0215_artifact_consent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', 'capability_requested', 'suggestion', 'finding', "
    "'workflow_notification'"
)
_AFTER = f"{_BEFORE}, 'artifact_owner_changed'"

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
        op.execute(f"DELETE FROM {table} WHERE event_type = 'artifact_owner_changed'")
    _recreate(_BEFORE)
