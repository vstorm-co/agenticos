"""Proactivity: suggestions, working hours, personal first messages and their limit (#2301).

The platform starts doing small things for a person on its own initiative, all of
it in background jobs: noticing a request they keep repeating, learning their
role from what their agent noted, writing the first messages their empty chat
offers. What it proposes waits in `suggestions` until the person decides, and a
dismissed one is kept so the same proposal is not made again.

Each organization caps what that work may spend per person per month
(`proactive_limit_usd`, $1 by default, zero to switch it off). The two new user
columns are nullable and nothing is backfilled: a person's first messages are
written by the first sweep that reaches them.

Revision ID: 0163_proactivity
Revises: 0162_teams_channel
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0163_proactivity"
down_revision: str | None = "0162_teams_channel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement', "
    "'artifact_version_published', 'resource_shared', 'budget_warning', "
    "'mcp_server_down', 'mcp_server_recovered', 'background_task_paused', "
    "'capability_requested'"
)
_WITH_SUGGESTIONS = f"{_EVENT_TYPE_VALUES}, 'suggestion'"

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
        "suggestions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('routine', 'agent', 'profile', 'role_pack')",
            name=op.f("suggestions_ck_suggestion_kind_check"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'dismissed')",
            name=op.f("suggestions_ck_suggestion_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("suggestions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("suggestions_user_id_fkey"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("suggestions_pkey")),
        sa.UniqueConstraint(
            "organization_id", "user_id", "dedupe_key", name="uq_suggestion_person_key"
        ),
    )
    op.create_index(
        op.f("suggestions_organization_id_idx"), "suggestions", ["organization_id"], unique=False
    )
    op.create_index(op.f("suggestions_user_id_idx"), "suggestions", ["user_id"], unique=False)

    op.add_column(
        "users",
        sa.Column("working_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("personal_starters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "users", sa.Column("personal_starters_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column(
            "proactive_limit_usd",
            sa.Numeric(precision=12, scale=6),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("organizations_ck_organization_proactive_limit_check"),
        "organizations",
        "proactive_limit_usd >= 0",
    )
    _event_types(_WITH_SUGGESTIONS)


def downgrade() -> None:
    op.execute("DELETE FROM notification_preferences WHERE event_type = 'suggestion'")
    op.execute("DELETE FROM notifications WHERE event_type = 'suggestion'")
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_constraint(
        op.f("organizations_ck_organization_proactive_limit_check"), "organizations", type_="check"
    )
    op.drop_column("organizations", "proactive_limit_usd")
    op.drop_column("users", "personal_starters_at")
    op.drop_column("users", "personal_starters")
    op.drop_column("users", "working_hours")
    op.drop_index(op.f("suggestions_user_id_idx"), table_name="suggestions")
    op.drop_index(op.f("suggestions_organization_id_idx"), table_name="suggestions")
    op.drop_table("suggestions")
