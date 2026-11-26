"""Scope chat-home presentation to deployment, organization and membership.

Nullable overrides preserve the current UI on upgrade. Personal choices live on
membership rather than the global user, so changing workspaces cannot leak a
preference into another organization. These settings never grant authority. Reminder frequency inherits in the same
way. Announcement expiry is a server clock limit; planned maintenance end is
information only and never reopens the deployment.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0347_console_experience"
down_revision: str = "0346_merge_console_matrix"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "deployment_settings",
        sa.Column("onboarding_reminders_available", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "deployment_settings",
        sa.Column("announcement_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "deployment_settings",
        sa.Column("maintenance_planned_end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("onboarding_reminders", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "organization_members",
        sa.Column("onboarding_reminders", postgresql.JSONB(none_as_null=True), nullable=True),
    )
    op.add_column(
        "deployment_settings", sa.Column("chat_home_available", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("chat_home_defaults", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "organization_members",
        sa.Column("chat_home_preferences", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organization_members", "onboarding_reminders")
    op.drop_column("organizations", "onboarding_reminders")
    op.drop_column("deployment_settings", "maintenance_planned_end_at")
    op.drop_column("deployment_settings", "announcement_expires_at")
    op.drop_column("deployment_settings", "onboarding_reminders_available")
    op.drop_column("organization_members", "chat_home_preferences")
    op.drop_column("organizations", "chat_home_defaults")
    op.drop_column("deployment_settings", "chat_home_available")
