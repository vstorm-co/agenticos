"""Join native account onboarding and skill-check migrations.

Keep both previously published migration paths intact and restore one head.
"""

revision: str = "0358_merge_native_and_checks"
down_revision: tuple[str, str] = (
    "0351_merge_context_onboarding",
    "0353_skill_check_verdict_version",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
