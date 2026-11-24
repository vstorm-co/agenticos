"""Verdicts that read criteria when no whole question flips.

A question passes only when every criterion it is graded on passes, so a
change that fixes one of several failing criteria flips no question and was
judged no change. An Improve attempt's verdict gains `criteria_better` - a
criterion its re-asks confirmed better and none worse - and
`criteria_worse`, a criterion confirmed worse with no question broken; a
session stopped on the second keeps `criteria_worse` as its stop reason.
A skill's improvement session shares both enums, so its attempts and runs
take the same values. A skill check's agent gains the same two states, and
`skill_check_agents` gains `criteria`, each criterion's counts over the
agent's held-out questions. An attempt keeps its criteria in `verdict_detail`, which is JSONB
already.

The downgrade reads both new verdicts and states, and the new stop reason,
as `no_change` - what they were judged before this revision - and drops the
column.

Revision ID: 0342_criterion_verdicts
Revises: 0341_workflow_run_tested_step
Create Date: 2026-11-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0342_criterion_verdicts"
down_revision: str = "0341_workflow_run_tested_step"
branch_labels: None = None
depends_on: None = None

_VERDICTS_BEFORE = "'better', 'no_change', 'regression', 'inconclusive'"
_VERDICTS = (
    "'better', 'criteria_better', 'no_change', 'criteria_worse', 'regression', 'inconclusive'"
)
_STOP_REASONS_BEFORE = (
    "'no_data', 'no_proposal', 'budget', 'inconclusive', 'regression', 'no_change', "
    "'max_iterations', 'repeat_candidate', 'permission', 'stale', 'stalled', 'proposal', "
    "'eval', 'superseded', 'knowledge_only', 'draft', 'expired'"
)
_STOP_REASONS = f"{_STOP_REASONS_BEFORE}, 'criteria_worse'"
_STATES_BEFORE = "'queued', 'running', 'better', 'no_change', 'within_noise', 'worse', 'unknown'"
_STATES = (
    "'queued', 'running', 'better', 'criteria_better', 'no_change', 'criteria_worse', "
    "'within_noise', 'worse', 'unknown'"
)


def _checks(verdicts: str, reasons: str, states: str) -> None:
    op.drop_constraint("ck_improvement_iteration_verdict", "improvement_iterations", type_="check")
    op.create_check_constraint(
        "ck_improvement_iteration_verdict",
        "improvement_iterations",
        f"verdict IS NULL OR verdict IN ({verdicts})",
    )
    op.drop_constraint("ck_improvement_run_stop_reason", "improvement_runs", type_="check")
    op.create_check_constraint(
        "ck_improvement_run_stop_reason",
        "improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({reasons})",
    )
    op.drop_constraint(
        "ck_skill_improvement_iteration_verdict", "skill_improvement_iterations", type_="check"
    )
    op.create_check_constraint(
        "ck_skill_improvement_iteration_verdict",
        "skill_improvement_iterations",
        f"verdict IS NULL OR verdict IN ({verdicts})",
    )
    op.drop_constraint(
        "ck_skill_improvement_run_stop_reason", "skill_improvement_runs", type_="check"
    )
    op.create_check_constraint(
        "ck_skill_improvement_run_stop_reason",
        "skill_improvement_runs",
        f"stop_reason IS NULL OR stop_reason IN ({reasons})",
    )
    op.drop_constraint("ck_skill_check_agent_state", "skill_check_agents", type_="check")
    op.create_check_constraint(
        "ck_skill_check_agent_state", "skill_check_agents", f"state IN ({states})"
    )


def upgrade() -> None:
    _checks(_VERDICTS, _STOP_REASONS, _STATES)
    op.add_column(
        "skill_check_agents",
        sa.Column(
            "criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("skill_check_agents", "criteria")
    op.execute(
        "UPDATE improvement_iterations SET verdict = 'no_change' "
        "WHERE verdict IN ('criteria_better', 'criteria_worse')"
    )
    op.execute(
        "UPDATE improvement_runs SET stop_reason = 'no_change' WHERE stop_reason = 'criteria_worse'"
    )
    op.execute(
        "UPDATE skill_improvement_iterations SET verdict = 'no_change' "
        "WHERE verdict IN ('criteria_better', 'criteria_worse')"
    )
    op.execute(
        "UPDATE skill_improvement_runs SET stop_reason = 'no_change' "
        "WHERE stop_reason = 'criteria_worse'"
    )
    op.execute(
        "UPDATE skill_check_agents SET state = 'no_change' "
        "WHERE state IN ('criteria_better', 'criteria_worse')"
    )
    _checks(_VERDICTS_BEFORE, _STOP_REASONS_BEFORE, _STATES_BEFORE)
