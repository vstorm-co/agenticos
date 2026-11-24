"""Join the upstream sync and T3 room migration histories.

The schema changes are already represented by both parents; this revision only
connects their histories so Alembic has one head.
"""

from collections.abc import Sequence

revision: str = "0325_merge_t3_rooms_v173"
down_revision: tuple[str, str] = (
    "0324_merge_t3_upstream_v173",
    "0311_room_submissions",
)
branch_labels: None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
