"""Keep a person's start goal and dismissal in the organization they belong to.

Nullable additions preserve existing memberships and the legacy account-level
walkthrough preference. Real task success is derived from completed chat runs.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0296_member_onboarding"
down_revision: str = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "organization_members", sa.Column("onboarding_goal", sa.String(16), nullable=True)
    )
    op.add_column(
        "organization_members",
        sa.Column("onboarding_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_org_member_onboarding_goal",
        "organization_members",
        "onboarding_goal IS NULL OR onboarding_goal IN ('meeting', 'document', 'compare')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_org_member_onboarding_goal", "organization_members", type_="check")
    op.drop_column("organization_members", "onboarding_dismissed_at")
    op.drop_column("organization_members", "onboarding_goal")
