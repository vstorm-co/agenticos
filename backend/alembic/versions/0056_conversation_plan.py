"""The plan a conversation is working to, so the next turn still has it.

A plan's store is one run's, and on this platform every chat message is a run.
So an agent wrote a three-step checklist, was asked to start on the first step,
and answered that there was no active plan and it had never created one - while
the transcript above it still showed the three steps (agenticos#1077).

`plan_items` is that checklist, as a JSONB list of `PlanItem` dumps: the run
seeds its store from this column and writes it back when it ends, the way
`reminder_state` (0036) carries a reminder cadence across the same boundary. It
is deliberately not the same field as `agent_runs.paused_state.plan`, which
carries a plan across an approval park *within* one run and is the newer copy on
a resume.

Nothing is backfilled. Null means no plan, which is the state of every
conversation whose agent does not bind the planning capability - most of them -
and of every conversation that existed before this column.

Revision ID: 0056_conversation_plan
Revises: 0055_sandbox_operations
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0056_conversation_plan"
# Re-parented onto 0056_backfill_rag_lookup_indexes rather than sharing
# 0055_sandbox_operations with it: both were cut from 0055 in parallel, which left
# two heads and failed every `alembic upgrade head`. The two are independent
# (collection indexes vs conversations.plan), so chaining them linearises the
# graph without a merge revision, which is what test_migration_chain.py wants.
down_revision: str | None = "0056_backfill_rag_lookup_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("plan_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "plan_items")
