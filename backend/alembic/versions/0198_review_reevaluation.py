"""Keep review provenance and notify changed suite verdicts.

Revision ID: 0198_review_reevaluation
Revises: 0197_improvement_rounds
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0198_review_reevaluation"
down_revision: str | None = "0197_improvement_rounds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', 'ingestion_completed', 'ingestion_failed', 'usage_report', 'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', 'artifact_version_published', 'resource_shared', 'budget_warning', 'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', 'eval_suite_failed', 'promotion_overridden', 'shared_change_applied', 'capability_requested', 'suggestion', 'finding', 'improvement_finished'"


def _checks(values: str) -> None:
    for table, name in (
        ("notifications", "ck_notifications_event_type"),
        ("notification_preferences", "ck_notification_preferences_event_type"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column(
        "eval_runs",
        sa.Column("review_metadata", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    _checks(_OLD + ", 'eval_suite_reevaluated'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'eval_suite_reevaluated'")
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'eval_suite_reevaluated'")
    _checks(_OLD)
    op.drop_column("eval_runs", "review_metadata")
