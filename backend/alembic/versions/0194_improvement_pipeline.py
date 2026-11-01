"""Freeze pipeline grading and attribute paid runs before any model call.

The lineage survives failure and cancellation, so session spend includes failed
steps and counts parent costs once rather than counting delegated attribution
again. Legacy sessions have no grading snapshot and are stopped as stale by the
new service. Notifications announce terminal states without evidence text.

Revision ID: 0194_improvement_pipeline
Revises: 0193_guard_judge_version
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0194_improvement_pipeline"
down_revision: str | None = "0193_guard_judge_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
# Event types main's own revisions added to these checks. This chain is applied
# to databases that already hold their rows, so a check written without them
# would refuse the upgrade.
_MAIN_EVENTS = (
    ", 'workflow_notification', 'artifact_owner_changed', "
    "'artifact_share_requested', 'workflow_log_alert'"
)

_EVENTS = "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', 'ingestion_completed', 'ingestion_failed', 'usage_report', 'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', 'artifact_version_published', 'resource_shared', 'budget_warning', 'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', 'eval_suite_failed', 'promotion_overridden', 'shared_change_applied', 'capability_requested', 'suggestion', 'finding'"


def checks(*, added: bool) -> None:
    events = _EVENTS + (", 'improvement_finished'" if added else "")
    for table, name in (
        ("notifications", "ck_notifications_event_type"),
        ("notification_preferences", "ck_notification_preferences_event_type"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({events}{_MAIN_EVENTS})")


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("improvement_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "agent_runs_improvement_run_id_fkey",
        "agent_runs",
        "improvement_runs",
        ["improvement_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("agent_runs_improvement_run_id_idx", "agent_runs", ["improvement_run_id"])
    op.add_column(
        "improvement_runs",
        sa.Column("pinned_scoring", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "improvement_runs",
        sa.Column("judge_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    checks(added=True)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'improvement_finished'")
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'improvement_finished'")
    checks(added=False)
    op.drop_column("improvement_runs", "judge_version_id")
    op.drop_column("improvement_runs", "pinned_scoring")
    op.drop_index("agent_runs_improvement_run_id_idx", "agent_runs")
    op.drop_constraint("agent_runs_improvement_run_id_fkey", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "improvement_run_id")
