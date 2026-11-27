"""Join reviewed cron/approvals with isolated script-call capture."""

from collections.abc import Sequence

revision: str = "0378_merge_script_reviewed"
down_revision: tuple[str, ...] = (
    "0377_merge_cron_reviewed",
    "0376_merge_script_calls",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
