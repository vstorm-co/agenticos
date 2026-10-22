"""An eval pool for background jobs (#2339).

An eval run holds its worker slot for the whole run, hours over a large
dataset, so in the agent pool ten of them left every API run and trigger fire
waiting. They get a pool of their own. A downgrade puts any eval job back in the
agent pool, where the worker before this revision looks for it.

Revision ID: 0173_eval_job_pool
Revises: 0172_eval_run_suite_check
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0173_eval_job_pool"
down_revision: str | None = "0172_eval_run_suite_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "background_jobs_pool_check"


def _pools(values: str) -> None:
    op.drop_constraint(op.f(_CHECK), "background_jobs", type_="check")
    op.create_check_constraint(op.f(_CHECK), "background_jobs", f"pool IN ({values})")


def upgrade() -> None:
    _pools("'agent', 'eval', 'ingest', 'system'")


def downgrade() -> None:
    op.execute("UPDATE background_jobs SET pool = 'agent' WHERE pool = 'eval'")
    _pools("'agent', 'ingest', 'system'")
