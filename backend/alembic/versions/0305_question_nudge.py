"""Remember that a parked question was reminded about once.

A nullable timestamp on `agent_runs`: the hourly sweep stamps it when it
reminds the chat that an `ask_user` question is still unanswered, so the
reminder goes out once instead of on every sweep until the question expires.
No backfill: every existing row is a run that has already been reminded about
as many times as the old code reminded anyone - never - so null, "not
reminded yet", is the true value for all of them.

This revision follows #47's `0304_visible_failover`. The branch is validated
with both migrations merged, so the chain has one head.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0305_question_nudge"
down_revision: str | None = "0304_visible_failover"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("question_nudged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "question_nudged_at")
