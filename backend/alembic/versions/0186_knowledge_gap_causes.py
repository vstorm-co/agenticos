"""Bad answers sorted by cause in an improvement session.

`improvement_runs.stage` gains `classifying` - the bad answers sorted into the
agent's faults, missing knowledge and non-problems - and `drafting`, the
missing knowledge drafted for a person to add. `stop_reason` gains
`knowledge_only`, a session whose every bad answer was missing knowledge, and
`draft`, a drafting step that failed with nothing left for the agent.
`improvement_iterations` gains the jobs that sorted and drafted each round.
`knowledge_gap_classifications` gains the classifier's one-sentence reason, and
`authoring_requests` the answers an improver must not read as evidence.

The downgrade stops every session on a step it no longer knows, as
superseded, and drops what this revision added.

Revision ID: 0186_knowledge_gap_causes
Revises: 0175_knowledge_gap_covered
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0186_knowledge_gap_causes"
down_revision: str | None = "0175_knowledge_gap_covered"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every value the improvement models allow after this revision, as the CHECK
# constraints and partial indexes spell them.
_STATUSES = (
    "'queued', 'running', 'ready', 'stopped', 'failed', 'cancelled', 'stale', "
    "'accepted', 'published', 'rejected'"
)
_ACTIVE = "'queued', 'running'"
_OPEN = "'queued', 'running', 'ready', 'accepted'"
_STAGES_BEFORE = "'analyzing', 'proposing', 'filtering', 'evaluating', 'judging'"
_STAGES = (
    "'analyzing', 'classifying', 'drafting', 'proposing', 'filtering', 'evaluating', 'judging'"
)
_STOP_REASONS_BEFORE = (
    "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', "
    "'permission', 'stale', 'stalled', 'proposal', 'eval', 'superseded'"
)
_STOP_REASONS = f"{_STOP_REASONS_BEFORE}, 'knowledge_only', 'draft'"
_VERDICTS = "'better', 'no_change', 'regression', 'inconclusive'"

_STAGE = "improvement_runs_ck_improvement_run_stage_check"
_STOP = "improvement_runs_ck_improvement_run_stop_reason_check"


def _checks(stages: str, reasons: str) -> None:
    op.drop_constraint(op.f(_STAGE), "improvement_runs", type_="check")
    op.create_check_constraint(
        op.f(_STAGE), "improvement_runs", f"stage IS NULL OR stage IN ({stages})"
    )
    op.drop_constraint(op.f(_STOP), "improvement_runs", type_="check")
    op.create_check_constraint(
        op.f(_STOP), "improvement_runs", f"stop_reason IS NULL OR stop_reason IN ({reasons})"
    )


def upgrade() -> None:
    _checks(_STAGES, _STOP_REASONS)
    for column in ("classify_job_id", "draft_job_id"):
        op.add_column(
            "improvement_iterations",
            sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            op.f(f"improvement_iterations_{column}_fkey"),
            "improvement_iterations",
            "background_jobs",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column("knowledge_gap_classifications", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(
        "authoring_requests",
        sa.Column(
            "excluded_message_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("authoring_requests", "excluded_message_ids")
    op.drop_column("knowledge_gap_classifications", "reason")
    for column in ("draft_job_id", "classify_job_id"):
        op.drop_constraint(
            op.f(f"improvement_iterations_{column}_fkey"),
            "improvement_iterations",
            type_="foreignkey",
        )
        op.drop_column("improvement_iterations", column)
    op.execute(
        "UPDATE improvement_runs SET status = 'stopped', stop_reason = 'superseded', "
        "finished_at = coalesce(finished_at, now()), "
        "stage = NULL WHERE stage IN ('classifying', 'drafting') AND status IN ('queued', 'running')"
    )
    op.execute(
        "UPDATE improvement_runs SET stage = NULL WHERE stage IN ('classifying', 'drafting')"
    )
    op.execute(
        "UPDATE improvement_runs SET stop_reason = 'no_proposal' "
        "WHERE stop_reason IN ('knowledge_only', 'draft')"
    )
    _checks(_STAGES_BEFORE, _STOP_REASONS_BEFORE)
