"""Shop live-agent handling on channel_sessions (D3 B67).

Revision ID: 0118_channel_session_shop_handling
Revises: 0117_shop_channel_bot_zalo
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0118_channel_session_shop_handling"
down_revision: str | None = "0117_shop_channel_bot_zalo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_sessions",
        sa.Column(
            "handling_mode",
            sa.String(length=20),
            nullable=False,
            server_default="ai",
        ),
    )
    op.add_column(
        "channel_sessions",
        sa.Column("claimed_by_user_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "channel_sessions",
        sa.Column("claimed_by_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "channel_sessions",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_channel_sessions_handling_mode",
        "channel_sessions",
        ["handling_mode"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_sessions_handling_mode", table_name="channel_sessions")
    op.drop_column("channel_sessions", "claimed_at")
    op.drop_column("channel_sessions", "claimed_by_name")
    op.drop_column("channel_sessions", "claimed_by_user_id")
    op.drop_column("channel_sessions", "handling_mode")
