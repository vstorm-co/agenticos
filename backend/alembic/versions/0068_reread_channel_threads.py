"""Forget that any channel thread has been read, so each is read once more.

`channel_sessions.thread_backfilled_at` means "we have read the thread above this
conversation". `0067` added it, and at that moment reading a thread meant reading
its *text*. Files came a few commits later.

So every session stamped in between carries a stamp that is true about a reader
that no longer exists: it claims the thread was read, and the thread's images
were never fetched. A session stamped one second after it was created - which is
what the stamp looks like on a healthy row - is exactly the shape this cannot
distinguish from a complete read, because the timestamp says when and not what.

Nulling the column is the honest state for all of them: nobody has read these
threads the way they are read now. Each is read once on its next turn and stamped
again. The cost is one extra platform call per active thread, once.

**This is the migration to copy whenever what "read the thread" means widens.**
A one-shot marker set before its reader was finished is the same defect three
times over in this area: the file drop that produced a conversation with a hole
in it, the "was the conversation just created" proxy that could never repair one,
and now a stamp that recorded an incomplete read. The marker has to be reset in
the same change that widens the reader, or the rows that most need re-reading are
precisely the ones that will not be.

Revision ID: 0068_reread_channel_threads
Revises: 0067_channel_thread_backfill
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068_reread_channel_threads"
down_revision: str | None = "0067_channel_thread_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE channel_sessions SET thread_backfilled_at = NULL")


def downgrade() -> None:
    """Nothing. The column is nullable and null is the state this restores to.

    A downgrade cannot put back timestamps it did not record, and inventing one
    would re-assert the claim this revision exists to withdraw. Re-reading a
    thread is idempotent, so the worst a downgrade costs is the same extra call.
    """
