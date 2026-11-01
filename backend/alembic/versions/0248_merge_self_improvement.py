"""Join the self-improvement head to main's, and give shared checks both sets of values.

The self-improvement branch built its chain from 0160 to 0215 beside main's own
0171 to 0247. Each chain rewrote the `event_type` checks on `notifications` and
`notification_preferences` and the `pool` check on `background_jobs` with only
its own values, so whichever ran last would have refused the other's rows. This
revision joins the two heads and writes each check with the values of both.

Revision ID: 0248_merge_self_improvement
Revises: 0215_main_128_merge, 0247_merge_deployment_workflows
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0248_merge_self_improvement"
down_revision: tuple[str, ...] = (
    "0215_main_128_merge",
    "0247_merge_deployment_workflows",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES = (
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
_POOLS = "'agent', 'eval', 'ingest', 'system', 'workflow'"


def upgrade() -> None:
    for table, name in (
        ("notifications", "ck_notifications_event_type"),
        ("notification_preferences", "ck_notification_preferences_event_type"),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({_EVENT_TYPES})")
    op.drop_constraint(op.f("background_jobs_pool_check"), "background_jobs", type_="check")
    op.create_check_constraint(
        op.f("background_jobs_pool_check"), "background_jobs", f"pool IN ({_POOLS})"
    )


def downgrade() -> None:
    """Nothing to undo: the checks stay a superset of what either chain wrote."""
