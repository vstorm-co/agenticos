"""Join personal work context with provider and onboarding migrations.

Both histories branch from the console avatar migration. Keeping their revisions
unchanged lets deployments upgrade from either release before this shared head.
"""

revision: str = "0351_merge_context_onboarding"
down_revision: tuple[str, str] = (
    "0349_personal_work_context",
    "0350_member_onboarding_progress",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
