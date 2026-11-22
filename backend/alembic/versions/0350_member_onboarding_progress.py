"""Record the current onboarding step per membership without inferring old progress."""

import sqlalchemy as sa

from alembic import op

revision: str = "0350_member_onboarding_progress"
down_revision: str = "0349_merge_console_and_providers"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "organization_members", sa.Column("onboarding_current_step", sa.String(64), nullable=True)
    )
    op.add_column(
        "organization_members",
        sa.Column("onboarding_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_org_member_onboarding_step",
        "organization_members",
        "onboarding_current_step IS NULL OR onboarding_current_step IN ('preferences.language', 'preferences.appearance', 'admin.workspace', 'admin.identity', 'admin.profile', 'admin.context', 'admin.subscriptions', 'admin.models', 'admin.tools', 'admin.team', 'admin.deployment', 'admin.organization', 'admin.task', 'member.welcome', 'member.profile', 'member.context', 'member.subscriptions', 'member.models', 'member.tools', 'member.task')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_org_member_onboarding_step", "organization_members", type_="check")
    op.drop_column("organization_members", "onboarding_updated_at")
    op.drop_column("organization_members", "onboarding_current_step")
