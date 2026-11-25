"""An Improve session keeps the held-out share it started with, and a skill's test set holds out all.

Every attempt of a session drew its held-out questions with the dataset's share as
it was at that moment, so editing the dataset moved what a running session
measures. The share is now stored on the session when it starts. Sessions that
already exist take the dataset's share as it is now: what they started with was
never recorded, and the current value is what their next attempt would have read.

A skill's test set is created holding out every question, because a skill check
asks only held-out questions; its share could still be lowered afterwards, and
the questions added since were then never asked. Its share is set back to one
and every one of its questions marked held out. Downgrade drops the session's
column and leaves the test sets as this revision left them: a question of a
skill's test set kept for training was never asked by any check.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0366_improvement_holdout_share"
down_revision: str | None = "0365_intercepted_call_external"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column("holdout_share", sa.Numeric(4, 3), nullable=True),
    )
    op.execute(
        "UPDATE improvement_runs SET holdout_share = datasets.improvement_holdout_share "
        "FROM datasets WHERE datasets.id = improvement_runs.dataset_id"
    )
    op.execute("UPDATE improvement_runs SET holdout_share = 0.5 WHERE holdout_share IS NULL")
    op.alter_column("improvement_runs", "holdout_share", nullable=False)
    op.execute(
        "UPDATE datasets SET improvement_holdout_share = 1 "
        "WHERE skill_id IS NOT NULL AND improvement_holdout_share <> 1"
    )
    op.execute(
        "UPDATE dataset_cases SET improvement_partition = 'holdout' "
        "WHERE improvement_partition <> 'holdout' "
        "AND dataset_id IN (SELECT id FROM datasets WHERE skill_id IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_column("improvement_runs", "holdout_share")
