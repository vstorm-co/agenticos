"""Join main's revisions after 0175 to the self-improvement head.

A database built from this branch is already past 0189, which joined main at
0175. Joining here rather than moving 0189 again lets such a database apply
0176 to 0178 as ordinary outstanding revisions instead of recording them as
done. This revision changes no tables.

Revision ID: 0215_main_128_merge
Revises: 0214_profile_key_column_again, 0178_project_workspace_moves
Create Date: 2026-10-28
"""

from collections.abc import Sequence

revision: str = "0215_main_128_merge"
down_revision: tuple[str, ...] = (
    "0214_profile_key_column_again",
    "0178_project_workspace_moves",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
