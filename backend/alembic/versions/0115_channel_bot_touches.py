"""How a channel bot answers: reaction, streaming, steps, thumbs, `/agent` (#2084).

Revision ID: 0115_channel_bot_touches
Revises: 0114_mcp_connection_audience
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0115_channel_bot_touches"
down_revision: str | None = "0114_mcp_connection_audience"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("channel_bots", sa.Column("ack_reaction", sa.String(64), nullable=True))
    op.add_column(
        "channel_bots", sa.Column("command_token_encrypted", sa.String(1000), nullable=True)
    )
    op.add_column(
        "channel_bots",
        sa.Column("stream_answers", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "channel_bots",
        sa.Column("rate_answers", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "channel_bots",
        sa.Column("step_display", sa.String(16), nullable=False, server_default="timeline"),
    )


def downgrade() -> None:
    op.drop_column("channel_bots", "step_display")
    op.drop_column("channel_bots", "rate_answers")
    op.drop_column("channel_bots", "stream_answers")
    op.drop_column("channel_bots", "command_token_encrypted")
    op.drop_column("channel_bots", "ack_reaction")
