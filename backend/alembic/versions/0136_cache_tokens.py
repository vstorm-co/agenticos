"""Keep a run's and a message's cache read and write tokens.

`input_tokens` includes them by Pydantic AI's convention, and they are priced
apart - a cache read at a fraction of the input rate, a write above it - so
without the split nobody can reconcile a run with the provider's console
(#2170). Zero for every existing run, null for every existing message: not
recorded, which a message's other usage columns already say the same way.

Revision ID: 0136_cache_tokens
Revises: 0135_run_tool_args_repaired
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0136_cache_tokens"
down_revision: str | None = "0135_run_tool_args_repaired"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("cache_read_tokens", "cache_write_tokens"):
        op.add_column(
            "agent_runs", sa.Column(column, sa.Integer(), nullable=False, server_default="0")
        )
        op.add_column("messages", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("cache_write_tokens", "cache_read_tokens"):
        op.drop_column("messages", column)
        op.drop_column("agent_runs", column)
