"""A heartbeat on a running run (#2301).

The process executing a run stamps `heartbeat_at` every few seconds, so the
stale-run sweep can end a run whose process died within minutes instead of
the six hours it waited for, and a chat stops saying "Working" over a turn
nothing is answering. Nullable and not backfilled: a run already finished
needs none, and one left `running` by a dead process ages from its start.

Revision ID: 0165_run_heartbeat
Revises: 0164_channel_next_steps
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0165_run_heartbeat"
down_revision: str | None = "0164_channel_next_steps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "heartbeat_at")
