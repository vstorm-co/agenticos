"""Keep what each stage of a skill check came to for every agent.

`skill_check_agents.stages` holds one entry per stage the agent ran, written when the
agent is judged: the stage's `kind`, `dataset_id` and `eval_run_id`, and how many of
its held-out questions were `compared`, `fixed`, `broken`, `unchanged` and left
`unknown`. A check's result then shows each agent's stages without comparing every
run again.

Checks judged before this keep an empty list, which reads as no counts kept: nothing
is backfilled, since the comparisons it would take are the ones this saves.

**Downgrade** drops the column; the counts are read again from the runs.

Revision ID: 0310_skill_check_stage_counts
Revises: 0309_skill_catch_up
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0310_skill_check_stage_counts"
down_revision: str | Sequence[str] | None = "0309_skill_catch_up"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_check_agents",
        sa.Column(
            "stages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("skill_check_agents", "stages")
