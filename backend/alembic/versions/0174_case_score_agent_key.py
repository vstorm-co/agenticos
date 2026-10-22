"""The review queue holds one score per case for each agent (#2376).

A score waiting for review used to stand for its case whichever agent
answered, so another agent's failure on the case pushed it out. Each score now
keeps the agent that answered - read from its run, or from its eval run when
the run is gone - and at most one score of each case and agent waits. Scores
written before could wait twice for one case and agent, when sent by hand or
when a verdict was withdrawn; the highest ranked of those keeps its place, a
graded one before one nothing graded and then the newest, and the rest leave
the queue undecided, as a replaced score does. A score with no agent to read
waits once per case, beside the others.

The backfill is one statement over the whole table, unbatched: it rewrites
every score that has an agent to read. The downgrade drops the column and the
index. Scores taken out of the queue stay out.

Revision ID: 0174_case_score_agent_key
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0174_case_score_agent_key"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

_INDEX = "uq_case_scores_pending_review"


def upgrade() -> None:
    op.add_column("case_scores", sa.Column("agent_id", PG_UUID(as_uuid=True), nullable=True))
    written = op.get_bind().execute(
        sa.text(
            """
            WITH keyed AS (
                SELECT score.id, score.dataset_id, score.case_id, score.passed,
                       score.created_at, score.review_state,
                       COALESCE(run.agent_id, eval.agent_id) AS agent_id
                FROM case_scores AS score
                LEFT JOIN agent_runs AS run ON run.id = score.run_id
                LEFT JOIN eval_runs AS eval ON eval.id = score.eval_run_id
            ),
            ranked AS (
                SELECT id, agent_id, review_state = 'pending' AND row_number() OVER (
                    PARTITION BY dataset_id, case_id, agent_id, review_state = 'pending'
                    ORDER BY passed IS NOT NULL DESC, created_at DESC, id DESC
                ) > 1 AS replaced
                FROM keyed
            )
            UPDATE case_scores
            SET agent_id = ranked.agent_id,
                review_state = CASE WHEN ranked.replaced THEN 'none' ELSE review_state END
            FROM ranked
            WHERE case_scores.id = ranked.id
              AND (ranked.agent_id IS NOT NULL OR ranked.replaced)
            RETURNING ranked.replaced
            """
        )
    )
    replaced = sum(1 for (was_replaced,) in written if was_replaced)
    logger.info("%d duplicate scores waiting for review left the queue undecided", replaced)
    op.create_index(
        _INDEX,
        "case_scores",
        ["dataset_id", "case_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("review_state = 'pending'"),
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="case_scores")
    op.drop_column("case_scores", "agent_id")
