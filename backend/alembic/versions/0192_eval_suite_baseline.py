"""A first measurement without a quality minimum sets a baseline, never a pass.

Reclassify retained passes with no minimum and no comparison so a pre-upgrade
result cannot keep a promotion gate open. This does not move environments back:
operators retain control of versions already promoted. A downgrade keeps those
results non-passing as inconclusive; restoring an invalid pass would reopen the bug.

Revision ID: 0192_eval_suite_baseline
Revises: 0191_eval_evidence_redaction
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0192_eval_suite_baseline"
down_revision: str | None = "0191_eval_evidence_redaction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(*, baseline: bool) -> None:
    values = "'pending', 'running', 'passed', 'failed', 'inconclusive', 'skipped', 'error'"
    if baseline:
        values += ", 'baseline_set'"
    op.drop_constraint("ck_eval_suite_result_status", "eval_suite_results", type_="check")
    op.create_check_constraint(
        "ck_eval_suite_result_status", "eval_suite_results", f"status IN ({values})"
    )


def upgrade() -> None:
    _check(baseline=True)
    op.execute("""
        UPDATE eval_suite_results SET status = 'baseline_set'
        WHERE status = 'passed'
          AND threshold->>'min_pass_rate' IS NULL
          AND summary IS NOT NULL
          AND summary->>'baseline_run_id' IS NULL
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE eval_suite_results
        SET status = 'inconclusive', reason = 'baseline_set',
            summary = jsonb_set(summary, '{message}',
                '"No minimum or comparison was set, so this result established a baseline without passing."'::jsonb)
        WHERE status = 'baseline_set'
    """)
    _check(baseline=False)
