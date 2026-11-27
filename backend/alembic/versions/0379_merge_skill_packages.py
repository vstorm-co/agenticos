"""Join complete skill packages with reviewed script, cron and approval changes."""

from collections.abc import Sequence

revision: str = "0379_merge_skill_packages"
down_revision: tuple[str, ...] = (
    "0378_merge_script_reviewed",
    "0376_skill_binary_resources",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
