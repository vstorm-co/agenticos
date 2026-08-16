"""The summary a conversation was compacted down to, and how far it reaches.

Compaction rewrites the messages of *one run*. Between turns the thread was
rebuilt from the transcript, so the summary was thrown away at the turn boundary
and the next turn bought another one over a history one turn longer — two
consecutive turns of a real conversation here each paid for a summary of the same
five messages, and the second announced itself as summarising nine (#49).

So the compacted history is written down. `summary_messages` is the message list
as the model last saw it, serialised the way a parked run's is; `summary_ordinal`
is the last transcript row it accounts for, so the next turn replays the summary
and only what has been said since. Null on both means no summary has run — every
conversation before this, and every one whose window is never reached.

Only a summary is kept. Dropping the oldest messages and clearing tool results
cost nothing to redo, and writing them down would make permanent a loss that is
currently reconsidered against the window on every turn.

`overhead_tokens` is the third column and answers a different question: what a
request carries before a single message - the instructions and every tool schema,
which no summary can compact away. It is measured from a response, so within one
run it is unknown until one arrives, which on a one-request chat turn is never.
Written down, the next turn starts knowing it, and a window with no room for a
summary is refused instead of buying one on every turn for ever.

Revision ID: 0034_conversation_summary
Revises: 0033_message_context_fill
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034_conversation_summary"
down_revision: str | None = "0033_message_context_fill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("summary_messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("conversations", sa.Column("summary_ordinal", sa.Integer(), nullable=True))
    op.add_column("conversations", sa.Column("overhead_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "overhead_tokens")
    op.drop_column("conversations", "summary_ordinal")
    op.drop_column("conversations", "summary_messages")
