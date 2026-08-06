"""Which run produced a turn

Revision ID: 0010_message_run_id
Revises: 0009_align_index_names
Create Date: 2026-08-06

`0006_message_usage` recorded what a turn cost and said plainly what was still
missing: "`agent_runs` holds the run's totals but nothing links a run to the
message it produced". This is that link, and it is what a run detail view is
built on - open a run from history and read the prompt, the reasoning, the tool
arguments and the answer it produced.

The alternative needed no migration and is quietly wrong: window `messages`
between the run's `started_at` and `ended_at`. Two runs started in one thread
interleave, so the first run's window contains the second's turns, and a run
that never wrote `ended_at` - cancelled, or still running - yields an empty
window that reads as "nothing was recorded". A drill-down whose errors are
invisible to its reader is worse than one that admits a gap.

Nullable, and no backfill. A turn written outside a run has no run to name: a
system message, or a prompt whose run row could not be opened. Guessing which
of a conversation's runs wrote which row is the windowing above under another
name, and there is no deployment holding history worth that guess.

`ON DELETE SET NULL`, not cascade. Deleting a run must not delete the
transcript - the words were still said, and the conversation is what somebody
reads them in. This is the same choice `agent_version_id` makes one column up.

The index serves the detail view's only query, `WHERE run_id = ?`. `messages`
is a hot insert table, so an index here is worth naming a reason for; this one
has a caller before it exists rather than after.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_message_run_id"
down_revision = "0009_align_index_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("messages_run_id_fkey"),
        "messages",
        "agent_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("messages_run_id_idx"), "messages", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("messages_run_id_idx"), table_name="messages")
    op.drop_constraint(op.f("messages_run_id_fkey"), "messages", type_="foreignkey")
    op.drop_column("messages", "run_id")
