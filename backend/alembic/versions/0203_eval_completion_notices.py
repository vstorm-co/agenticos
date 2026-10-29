"""Notify manual test and question-generation completion.

Revision ID: 0203_eval_completion_notices
Revises: 0202_knowledge_retrieval
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0203_eval_completion_notices"
down_revision: str | None = "0202_knowledge_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
_OLD = "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', 'ingestion_completed', 'ingestion_failed', 'usage_report', 'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', 'artifact_version_published', 'resource_shared', 'budget_warning', 'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', 'eval_suite_failed', 'promotion_overridden', 'shared_change_applied', 'capability_requested', 'suggestion', 'finding', 'improvement_finished', 'eval_suite_reevaluated'"


def _checks(values: str) -> None:
    for table, name in (
        ("notifications", "ck_notifications_event_type"),
        ("notification_preferences", "ck_notification_preferences_event_type"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    _checks(_OLD + ", 'eval_run_finished', 'case_generation_finished'")


def downgrade() -> None:
    for table in ("notifications", "notification_preferences"):
        op.execute(
            f"DELETE FROM {table} WHERE event_type IN ('eval_run_finished', 'case_generation_finished')"
        )
    _checks(_OLD)
