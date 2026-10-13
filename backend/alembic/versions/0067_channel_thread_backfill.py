"""Record when a channel session's thread was read from the platform.

A bot mentioned in a thread that was already running holds nothing above the
mention: a conversation here is built from what this deployment *received*, so
the turns before the bot arrived are simply absent. It answered as though the
thread were empty, and said so confidently.

The turn that notices now reads the thread once. **Which turn that is needed a
column.** The first version keyed it on "the conversation was just created",
which is a proxy for "we have never read this thread" - and the two come apart
exactly where it matters. A session opened while the bot was dropping every
message with a file on it exists, holds a handful of useless turns, and could
never be repaired: the proxy answered "not new" for ever, so the read never ran
and the thread above stayed invisible however many times somebody asked.

Nullable with no backfill, and that is the whole point rather than an omission:
every session written before this column reads null, which is the truth about
them - nobody has read their thread - so each is read once on its next turn and
then stamped. A `server_default` of `now()` would have declared them all done
and preserved the defect it was added to fix.

A timestamp rather than a boolean because it costs the same and answers "when",
which is the question somebody asks when a transcript looks shorter than the
thread it belongs to.

Revision ID: 0067_channel_thread_backfill
Revises: 0066_mcp_connection_last_tools
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0067_channel_thread_backfill"
down_revision: str | None = "0066_mcp_connection_last_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_sessions",
        sa.Column("thread_backfilled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("channel_sessions", "thread_backfilled_at")
