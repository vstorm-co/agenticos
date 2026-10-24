"""Pin the baseline of eval runs written before it was kept on them (#2360).

A run that named no baseline was compared with whatever the latest run of the
version before it was each time it was read, so its verdict moved with every
publish. A run now keeps its baseline as an arm of its own from the start. A run
written before that and read since kept that comparison in `outcome`; it is
pinned to the run named there, so it keeps saying what it said. A run never read
has nothing to pin and is the first result of its version.

The downgrade leaves the pins in place: a run's `baseline_run_id` set here cannot
be told from one its starter named, and the code before this revision reads both
the same way.

Revision ID: 0184_eval_run_pinned_baseline
Revises: 0176_eval_case_fault
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0184_eval_run_pinned_baseline"
down_revision: str | None = "0176_eval_case_fault"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE eval_runs AS run
        SET baseline_run_id = (run.outcome -> 'baseline' ->> 'run_id')::uuid
        WHERE run.baseline_run_id IS NULL
          AND run.outcome -> 'baseline' ->> 'run_id' IS NOT NULL
          AND (run.outcome -> 'baseline' ->> 'run_id')::uuid <> run.id
          AND NOT EXISTS (
            SELECT 1 FROM eval_run_arms AS arm
            WHERE arm.eval_run_id = run.id AND arm.role = 'baseline'
          )
          AND EXISTS (
            SELECT 1 FROM eval_runs AS earlier
            WHERE earlier.id = (run.outcome -> 'baseline' ->> 'run_id')::uuid
              AND earlier.organization_id = run.organization_id
          )
        """
    )


def downgrade() -> None:
    pass
