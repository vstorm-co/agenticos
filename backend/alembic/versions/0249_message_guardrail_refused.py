"""Mark on the message itself that a guardrail stopped its turn (#2578).

A later turn's history withholds the prompt of a turn a guardrail stopped. The
first cut read that off `messages.run_id` -> `agent_runs.status`, and the run is
not a lasting record: run retention deletes a `guardrail_blocked` run like any
other finished one, `messages.run_id` is `ON DELETE SET NULL`, and the row then
read as an ordinary prompt - the next turn replayed what the input edge had
stopped. `messages.guardrail_refused` keeps the refusal on the row, which
outlives the run.

The backfill marks every row of a run that ended `guardrail_blocked` - the
prompt, and the answer row whose steers are withheld with it. A run retention
already deleted cannot be read back: its rows were replayed before this change
and stay unmarked, which is the gap this column closes from here on.

The downgrade drops the column; the refusals it recorded are still on the runs
that have not been retired.

Revision ID: 0249_message_guardrail_refused
Revises: 0248_drop_refused_turn_summaries
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0249_message_guardrail_refused"
down_revision: str | Sequence[str] | None = "0248_drop_refused_turn_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MARK_REFUSED = """
        UPDATE messages AS m
        SET guardrail_refused = true
        FROM agent_runs AS r
        WHERE r.id = m.run_id
          AND r.status = 'guardrail_blocked'
          AND NOT m.guardrail_refused
"""
"""Read by its integration test as well, which runs it over rows the models wrote."""


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("guardrail_refused", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(MARK_REFUSED)


def downgrade() -> None:
    op.drop_column("messages", "guardrail_refused")
