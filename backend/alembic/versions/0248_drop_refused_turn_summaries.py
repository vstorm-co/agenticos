"""Drop the stored summaries that may quote a turn a guardrail refused (#2578).

Before #2578 a conversation's history replayed every transcript row, including
the prompt of a run that ended `guardrail_blocked` and the attachment briefing
kept beside it. A later turn that compacted its history stored the result in
`conversations.summary_messages`, and compaction keeps the most recent messages
word for word, so that blob can still hold the refused text. The history now
withholds a refused prompt from the transcript rows it reads, but the stored
summary is replayed as it is.

This clears `summary_messages` and `summary_ordinal` on every conversation whose
summary reaches past a refused prompt: a user message, at or before
`summary_ordinal`, whose run ended `guardrail_blocked`. The next turn rebuilds
the history from the transcript, where the filter applies, and buys a new
summary if it needs one; turns past the transcript window that only the summary
still recalled are not read back. A summary written after this change does not
hold refused text - a blocked run stores none, and a later run is handed the
filtered history - so this runs once. Two edges it does not reach: a turn that
started in the moment another was still being screened, and a run parked on an
approval before the upgrade, which resumes with the history it was parked with.

The downgrade does nothing: the cleared summaries are not kept anywhere, and a
conversation without one is the state every thread starts in.

Revision ID: 0248_drop_refused_turn_summaries
Revises: 0247_merge_deployment_workflows
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0248_drop_refused_turn_summaries"
down_revision: str | Sequence[str] | None = "0247_merge_deployment_workflows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DROP_SUMMARIES = """
        UPDATE conversations AS c
        SET summary_messages = NULL, summary_ordinal = NULL
        WHERE c.summary_ordinal IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM messages AS m
            JOIN agent_runs AS r ON r.id = m.run_id
            WHERE m.conversation_id = c.id
              AND m.role = 'user'
              AND m.ordinal <= c.summary_ordinal
              AND r.status = 'guardrail_blocked'
          )
"""
"""Read by its integration test as well, which runs it over rows the models wrote."""


def upgrade() -> None:
    op.execute(DROP_SUMMARIES)


def downgrade() -> None:
    pass
