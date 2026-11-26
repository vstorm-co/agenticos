"""Say when a skill check's agent is unknown for want of questions.

An agent whose runs graded every answer, but whose held-out questions fell short
of the five a result needs, was recorded `inconclusive` - the reason for a run
that could not grade every answer - so three confirmed fixes and nothing broken
read as a check that could not tell. `skill_check_agents.unknown_reason` takes
`too_few_questions` for it.

**Downgrade** reads `too_few_questions` as `inconclusive`, the value it replaces.

Revision ID: 0351_skill_check_too_few
Revises: 0350_skill_check_families
Create Date: 2026-11-19
"""

from alembic import op

revision: str = "0351_skill_check_too_few"
down_revision: str = "0350_skill_check_families"
branch_labels: None = None
depends_on: None = None

_TABLE = "skill_check_agents"
_REASON = "skill_check_agents_ck_skill_check_agent_reason_check"
_REASONS = (
    "'no_questions', 'no_access', 'no_budget', 'no_published_version', 'inconclusive', "
    "'failed', 'unscorable', 'all_evidence', 'cancelled', 'own_not_asked'"
)


def _reasons(allowed: str) -> None:
    op.drop_constraint(op.f(_REASON), _TABLE, type_="check")
    op.create_check_constraint(
        op.f(_REASON), _TABLE, f"unknown_reason IS NULL OR unknown_reason IN ({allowed})"
    )


def upgrade() -> None:
    _reasons(f"{_REASONS}, 'too_few_questions'")


def downgrade() -> None:
    op.execute(
        f"UPDATE {_TABLE} SET unknown_reason = 'inconclusive' "
        "WHERE unknown_reason = 'too_few_questions'"
    )
    _reasons(_REASONS)
