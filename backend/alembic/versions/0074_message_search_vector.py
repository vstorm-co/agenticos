"""Full-text search over message bodies, for the `conversation_search` capability.

A generated `tsvector` beside `messages.content` and a GIN index on it, which is
what lets an agent find a past conversation by what was said in it rather than by
its title (#789). `conversations.title` was already searchable with `ILIKE`, and a
title is generated from the first turn - so "what did we decide about the Q3
pricing" matched nothing unless somebody happened to open with those words.

**`simple`, not `english`, and that is a decision rather than a default.** The
configuration is fixed at the column and cannot be changed without rewriting the
table, so it has to be right for every deployment rather than for ours. `english`
would stem and drop stopwords for one language and mangle or ignore the rest;
PostgreSQL ships no Polish dictionary at all, so half this product's users would
get a measurably worse search than the other half with nothing saying so. `simple`
folds case and splits on word boundaries for every language identically - the
"proper word matching, not an `ILIKE`" this exists for - and buys that evenness by
not matching `meeting` to `meetings`. The tool description says so, so the model
can try the other form rather than concluding nothing was said.

Generated rather than maintained by a trigger: a trigger is a second place the
truth lives, and an `UPDATE` that forgets it leaves a row that can never be found
again. The column is `STORED`, so writing a message pays the tokenisation once and
every search reads the index.

**It rewrites the table.** Adding a stored generated column takes an ACCESS
EXCLUSIVE lock and tokenises every existing row, so on a deployment with a large
`messages` table this is a maintenance window rather than a rolling upgrade. Worth
knowing before running it against one; the alternative - a nullable column
backfilled in batches - is a second mechanism and a half-indexed table in the
meantime, which is a search that silently misses old conversations.

Revision ID: 0074_message_search_vector
Revises: 0073_agent_memory_files
Create Date: 2026-09-06

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_message_search_vector"
down_revision: str | None = "0073_agent_memory_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `'simple'::regconfig` rather than `'simple'`: the two-argument `to_tsvector`
    # is IMMUTABLE and the one-argument form is only STABLE, and a generated
    # column refuses anything that is not IMMUTABLE. Written without the cast the
    # statement fails, which is the good outcome; written as a trigger it would
    # have silently depended on `default_text_search_config`.
    op.execute(
        "ALTER TABLE messages ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(content, ''))) STORED"
    )
    op.execute("CREATE INDEX messages_search_vector_idx ON messages USING gin (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS messages_search_vector_idx")
    op.execute("ALTER TABLE messages DROP COLUMN search_vector")
