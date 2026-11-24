"""Join the self-improvement integration and the released Discord chain.

Keep both histories intact so databases already running either branch apply
the outstanding revisions instead of recording those revisions as completed.

Revision ID: 0251_merge_improvement_discord
Revises: 0248_merge_self_improvement, 0250_discord_channel
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "0251_merge_improvement_discord"
down_revision: tuple[str, ...] = (
    "0248_merge_self_improvement",
    "0250_discord_channel",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
