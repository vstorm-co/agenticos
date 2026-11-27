"""Join reviewed approvals and the croniter 7 schedule compatibility migration."""

from collections.abc import Sequence

revision: str = "0377_merge_cron_reviewed"
down_revision: tuple[str, ...] = (
    "0376_merge_reviewed_approvals",
    "0376_croniter7_schedules",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
