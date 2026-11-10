"""Hold a guard's judge version as firmly as its dataset and scoring.

Retain version identities after deletion so missing judges fail closed. Existing
runs remain unpinned: an old pass cannot attest to a newly pinned judge. Guards
are backfilled to the configured judge's current publication; a missing version
stays null and grading refuses until an authorized pin move. No environment is
moved by this migration.

Revision ID: 0193_guard_judge_version
Revises: 0192_eval_suite_baseline
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0193_guard_judge_version"
down_revision: str | None = "0192_eval_suite_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_suites",
        sa.Column("pinned_judge_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "eval_runs", sa.Column("judge_version_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "eval_runs",
        sa.Column("judge_pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("""
        UPDATE eval_suites AS s SET pinned_judge_version_id = a.current_version_id
        FROM agents AS a
        WHERE s.pinned_dataset_version IS NOT NULL AND a.organization_id = s.organization_id
          AND a.kind = 'judge'
          AND ((s.pinned_scoring->'judge'->>'agent_id' IS NOT NULL
                AND a.id::text = s.pinned_scoring->'judge'->>'agent_id')
            OR (s.pinned_scoring->'judge'->>'agent_id' IS NULL AND a.system_key = 'eval_judge'))
    """)


def downgrade() -> None:
    op.drop_column("eval_runs", "judge_pinned")
    op.drop_column("eval_runs", "judge_version_id")
    op.drop_column("eval_suites", "pinned_judge_version_id")
