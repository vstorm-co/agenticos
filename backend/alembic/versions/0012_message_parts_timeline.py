"""Record an assistant turn's order, instead of having a client invent one.

A message row said what a turn contained and could not say when. `content` held
the text, `thinking` the reasoning and `tool_calls` the calls - three buckets, no
sequence - so a client replaying a conversation had to reconstruct an order, and
the only one it could reconstruct was reasoning, then every tool, then the answer.

That is not what a turn looks like. A model that writes "here are the charts",
draws three, and then summarises them has two blocks of text with the tools
between them, and a single `content` column has room for one: the introduction was
dropped on save, and the summary reappeared above the charts it was written about.
So the conversation somebody watched and the one they reopened were different
documents, and the difference grew with the number of steps in the turn.

`parts` is the sequence as it was streamed, so both surfaces render the same array
rather than agreeing by coincidence. Entries are `{"type": "text"|"thinking",
"text": ...}` or `{"type": "tool", "tool_call_id": ...}`; a tool's arguments and
result stay in `tool_calls`, because a call written twice is a call that disagrees
with itself the first time one is re-run.

Nullable and deliberately not backfilled. `content`, `thinking` and `tool_calls`
are untouched and still carry the turn's text, so an older row remains readable -
but its order was never recorded and cannot be recovered, and a backfill would be
this migration guessing the same order the client used to guess. Null is the
honest value, and it is what tells a client to fall back rather than to render an
empty turn.

Revision ID: 0012_message_parts_timeline
Revises: 0011_message_run_id
Create Date: 2026-08-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_message_parts_timeline"
down_revision: str | None = "0011_message_run_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("parts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "parts")
