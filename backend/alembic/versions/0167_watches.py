"""Watches: the proactive look pointed at a person's own connections (#2301).

A person picks one of their MCP connections, says what to look for and how
often, and what is new arrives as a finding - a suggestion of kind `finding`,
tied to the watch and marked urgent where it should not wait for the morning.
An organization allows it, names the catalog servers it may read, and sets how
often a watch may run at most. Off for every organization until turned on.

Revision ID: 0167_watches
Revises: 0166_proactivity_settings
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0167_watches"
down_revision: str | None = "0166_proactivity_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', "
    "'capability_requested', 'suggestion'"
)
_WITH_FINDINGS = f"{_EVENT_TYPE_VALUES}, 'finding'"

_EVENT_TYPE_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _EVENT_TYPE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.create_table(
        "watches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preset_key", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("exclusions", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("urgent", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("interval_minutes >= 15", name="ck_watch_interval_minutes"),
    )
    op.create_index("watches_organization_id_idx", "watches", ["organization_id"])
    op.create_index("watches_user_id_idx", "watches", ["user_id"])
    op.create_index("watches_connection_id_idx", "watches", ["connection_id"])
    op.create_index("watches_next_run_at_idx", "watches", ["next_run_at"])

    op.add_column(
        "organizations",
        sa.Column(
            "proactive_watches_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "proactive_watch_min_minutes",
            sa.Integer(),
            server_default=sa.text("60"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_organization_watch_min_minutes", "organizations", "proactive_watch_min_minutes >= 15"
    )

    op.add_column(
        "suggestions",
        sa.Column(
            "watch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("watches.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("suggestions_watch_id_idx", "suggestions", ["watch_id"])
    op.add_column(
        "suggestions",
        sa.Column("urgent", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_constraint("ck_suggestion_kind", "suggestions", type_="check")
    op.create_check_constraint(
        "ck_suggestion_kind",
        "suggestions",
        "kind IN ('routine', 'agent', 'profile', 'role_pack', 'finding')",
    )
    _event_types(_WITH_FINDINGS)


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'finding'")
    op.execute("DELETE FROM notifications WHERE event_type = 'finding'")
    _event_types(_EVENT_TYPE_VALUES)
    op.execute("DELETE FROM suggestions WHERE kind = 'finding'")
    op.drop_constraint("ck_suggestion_kind", "suggestions", type_="check")
    op.create_check_constraint(
        "ck_suggestion_kind",
        "suggestions",
        "kind IN ('routine', 'agent', 'profile', 'role_pack')",
    )
    op.drop_column("suggestions", "urgent")
    op.drop_index("suggestions_watch_id_idx", table_name="suggestions")
    op.drop_column("suggestions", "watch_id")
    op.drop_constraint("ck_organization_watch_min_minutes", "organizations", type_="check")
    for column in (
        "proactive_watch_min_minutes",
        "proactive_watches_enabled",
    ):
        op.drop_column("organizations", column)
    op.drop_table("watches")
