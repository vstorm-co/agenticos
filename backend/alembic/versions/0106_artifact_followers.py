"""Let a person follow an artifact and be told when a new version lands (#1977).

A table of followers, and the new event type added to the two CHECK
constraints that hold the notification vocabulary.

Revision ID: 0106_artifact_followers
Revises: 0105_workspace_directories
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0106_artifact_followers"
down_revision: str | None = "0105_workspace_directories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPE_VALUES = (
    "'budget_exceeded', 'approval_requested', 'run_completed', 'run_failed', "
    "'ingestion_completed', 'ingestion_failed', 'usage_report', "
    "'agent_usage_report', 'security_event', 'configuration_changed', 'announcement'"
)
_WITH_ARTIFACTS = f"{_EVENT_TYPE_VALUES}, 'artifact_version_published'"

_CONSTRAINTS = (
    ("notifications", "ck_notifications_event_type"),
    ("notification_preferences", "ck_notification_preferences_event_type"),
)


def _event_types(values: str) -> None:
    for table, name in _CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"event_type IN ({values})")


def upgrade() -> None:
    op.create_table(
        "artifact_followers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "user_id", name="uq_artifact_follower"),
    )
    op.create_index(
        "artifact_followers_artifact_id_idx", "artifact_followers", ["artifact_id"], unique=False
    )
    op.create_index(
        "artifact_followers_user_id_idx", "artifact_followers", ["user_id"], unique=False
    )
    _event_types(_WITH_ARTIFACTS)


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE event_type = 'artifact_version_published'")
    op.execute(
        "DELETE FROM notification_preferences WHERE event_type = 'artifact_version_published'"
    )
    _event_types(_EVENT_TYPE_VALUES)
    op.drop_index("artifact_followers_user_id_idx", table_name="artifact_followers")
    op.drop_index("artifact_followers_artifact_id_idx", table_name="artifact_followers")
    op.drop_table("artifact_followers")
