"""When an organization's MCP server stopped answering, and the two notifications (#2100).

Revision ID: 0119_mcp_server_alerts
Revises: 0118_tool_call_mcp_connection
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0119_mcp_server_alerts"
down_revision: str | None = "0118_tool_call_mcp_connection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning'"
)
_WITH_MCP = f"{_EVENT_TYPE_VALUES}, 'mcp_server_down', 'mcp_server_recovered'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.add_column(
        "mcp_connections",
        sa.Column("unreachable_since", sa.DateTime(timezone=True), nullable=True),
    )
    _event_types(_WITH_MCP)


def downgrade() -> None:
    for table in ("notifications", "notification_preferences"):
        op.execute(
            f"DELETE FROM {table} WHERE event_type IN ('mcp_server_down', 'mcp_server_recovered')"
        )
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_column("mcp_connections", "unreachable_since")
