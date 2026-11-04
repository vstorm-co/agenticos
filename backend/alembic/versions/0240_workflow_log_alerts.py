"""Alert rules on a workflow's log, and the notification type they send.

`workflow_log_alert_rules` holds one row per rule of a workflow: the outcomes and
optional step and text it counts, a threshold within a window of 5, 15, 30, 60 minutes,
4 or 24 hours, an audience of roles (`admins`, `owner`, `chosen`) with the chosen
members' ids, and `last_fired_at`, which keeps a rule to one alert per window.
`workflow_log_alert_firings` records each alert a rule sent. Both cascade with the
workflow and the organization (a firing with its rule); `created_by_user_id` is cleared
when its user is deleted. The downgrade drops both tables.

The new notification type, `workflow_log_alert`, goes into the CHECKs on
`notifications.event_type` and `notification_preferences.event_type` as
`0217_artifact_share_requests` did for its type; the downgrade deletes rows of the new
type before restoring the narrower CHECKs.

Revision ID: 0240_workflow_log_alerts
Revises: 0239_workflow_log_entry_seq
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0240_workflow_log_alerts"
down_revision: str | Sequence[str] | None = "0239_workflow_log_entry_seq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', "
    "'capability_requested', 'suggestion', 'finding', "
    "'workflow_notification', 'artifact_owner_changed', 'artifact_share_requested'"
)
_AFTER = f"{_BEFORE}, 'workflow_log_alert'"

_CHECKS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _recreate(values: str) -> None:
    for table, name in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.create_table(
        "workflow_log_alert_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("outcomes", postgresql.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("node_instance_id", sa.UUID(), nullable=True),
        sa.Column("message_contains", sa.String(length=200), nullable=True),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("audience", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("user_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "threshold BETWEEN 1 AND 1000",
            name=op.f("workflow_log_alert_rules_ck_threshold_check"),
        ),
        sa.CheckConstraint(
            "window_minutes IN (5, 15, 30, 60, 240, 1440)",
            name=op.f("workflow_log_alert_rules_ck_window_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("workflow_log_alert_rules_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("workflow_log_alert_rules_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("workflow_log_alert_rules_created_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_log_alert_rules_pkey")),
    )
    op.create_index(
        "ix_workflow_log_alert_rules_workflow",
        "workflow_log_alert_rules",
        ["organization_id", "workflow_id"],
        unique=False,
    )
    op.create_table(
        "workflow_log_alert_firings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column(
            "fired_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["workflow_log_alert_rules.id"],
            name=op.f("workflow_log_alert_firings_rule_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("workflow_log_alert_firings_pkey")),
    )
    op.create_index(
        "ix_workflow_log_alert_firings_rule",
        "workflow_log_alert_firings",
        ["rule_id", sa.literal_column("fired_at DESC")],
        unique=False,
    )
    _recreate(_AFTER)


def downgrade() -> None:
    for table, _name in _CHECKS:
        op.execute(f"DELETE FROM {table} WHERE event_type = 'workflow_log_alert'")
    _recreate(_BEFORE)
    op.drop_index("ix_workflow_log_alert_firings_rule", table_name="workflow_log_alert_firings")
    op.drop_table("workflow_log_alert_firings")
    op.drop_index("ix_workflow_log_alert_rules_workflow", table_name="workflow_log_alert_rules")
    op.drop_table("workflow_log_alert_rules")
