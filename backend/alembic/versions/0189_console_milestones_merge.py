"""Join self-improvement with the console's proactivity and media releases.

Both histories extend the notification event check. Their upgrades replace the
whole check, so the last parent applied would otherwise reject the other
milestone's events. The joined schema accepts every event in both histories.
The downgrade keeps this union: both parent histories remain applied at the
merge boundary, so their events still need to be representable.

Revision ID: 0189_console_milestones_merge
Revises: 0188_self_improvement_merge, 0170_generated_media
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0189_console_milestones_merge"
down_revision: tuple[str, ...] = ("0188_self_improvement_merge", "0170_generated_media")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', "
    "'announcement', 'artifact_version_published', 'resource_shared', "
    "'budget_warning', 'mcp_server_down', 'mcp_server_recovered', "
    "'background_task_paused', 'eval_suite_failed', 'promotion_overridden', "
    "'shared_change_applied', 'capability_requested', 'suggestion', 'finding'"
)


def upgrade() -> None:
    for table, name in (
        ("notifications", "ck_notifications_event_type"),
        ("notification_preferences", "ck_notification_preferences_event_type"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({_EVENTS})")


def downgrade() -> None:
    pass
