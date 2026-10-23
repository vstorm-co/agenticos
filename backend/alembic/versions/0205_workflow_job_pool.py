"""Give workflow nodes a worker pool of their own.

`workflow-dispatch-node` jobs ran in the agent pool, where a fan-out held the slots
that agent runs and trigger fires wait for. They now run in a `workflow` pool, so
the `pool` check accepts it. Jobs already queued in the agent pool are moved over,
or no worker serving only `workflow` would ever claim them and an agent-only one
would run them in the wrong pool.

Revision ID: 0205_workflow_job_pool
Revises: 0204_workflow_call_unique
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0205_workflow_job_pool"
down_revision: str | Sequence[str] | None = "0204_workflow_call_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "pool IN ('agent', 'ingest', 'system')"
_AFTER = "pool IN ('agent', 'ingest', 'system', 'workflow')"


def upgrade() -> None:
    op.drop_constraint(op.f("background_jobs_pool_check"), "background_jobs", type_="check")
    op.create_check_constraint(op.f("background_jobs_pool_check"), "background_jobs", _AFTER)
    op.execute(
        "UPDATE background_jobs SET pool = 'workflow' "
        "WHERE kind = 'workflow-dispatch-node' AND status = 'queued'"
    )


def downgrade() -> None:
    op.execute("UPDATE background_jobs SET pool = 'agent' WHERE pool = 'workflow'")
    op.drop_constraint(op.f("background_jobs_pool_check"), "background_jobs", type_="check")
    op.create_check_constraint(op.f("background_jobs_pool_check"), "background_jobs", _BEFORE)
