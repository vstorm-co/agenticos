"""Merge T3OS feature revisions and upstream v1.60.0 migration heads."""

from collections.abc import Sequence

revision: str = "0302_merge_upstream"
down_revision: tuple[str, str] = (
    "0299_merge_personal_composio",
    "0301_conversation_forks",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
