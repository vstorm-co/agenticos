"""A parked chat run remembers that its chat was told it could not continue.

Revision ID: 0255_run_chat_notice_sent_at
Revises: 0254_model_profile_region
Create Date: 2026-11-03

A decision made outside a chat continues the run in that chat. When the platform
definitely refuses the decider, the chat gets one notice, and the hourly safety
net that ends decided-but-never-continued runs must not tell it a second time.
`agent_runs.chat_notice_sent_at` is that record. `mark_running` clears it, so each
park is announced at most once.

It is a column and not a key in `paused_state` because `PausedRunState` is
`extra="forbid"`: a key there would make the run unreadable to an older process
on a rollback or a rolling deploy. A nullable column is ignored by one.

There is no backfill (a run parked before this has told nobody anything) and no
index (the safety net reads the column only on a run it has already claimed).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0255_run_chat_notice_sent_at"
down_revision: str | None = "0254_model_profile_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("chat_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "chat_notice_sent_at")
