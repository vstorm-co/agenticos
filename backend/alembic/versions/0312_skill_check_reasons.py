"""Say more precisely why an agent of a skill check could not be checked.

`skill_check_agents.unknown_reason` takes four more reasons:

- `unscorable`: nothing its questions are graded with can decide one;
- `all_evidence`: every question came from the conversations the change learned from;
- `cancelled`: the check was stopped before the agent's runs finished;
- `own_not_asked`: a quick check left the agent's own questions unasked once the
  skill's made it worse, and a person's verdict has since taken that back.

`skill_check_agents.sample` takes `own_not_asked` for those questions, so the row no
longer says they were asked.

**Downgrade** reads the new reasons as `failed`, and `own_not_asked` as
`own_questions`, the values they replace.

Revision ID: 0312_skill_check_reasons
Revises: 0311_skill_fk_indexes
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0312_skill_check_reasons"
down_revision: str | Sequence[str] | None = "0311_skill_fk_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "skill_check_agents"
_REASON = "skill_check_agents_ck_skill_check_agent_reason_check"
_SAMPLE = "skill_check_agents_ck_skill_check_agent_sample_check"
_REASONS = (
    "'no_questions', 'no_access', 'no_budget', 'no_published_version', 'inconclusive', 'failed'"
)
_NEW_REASONS = "'unscorable', 'all_evidence', 'cancelled', 'own_not_asked'"
_SAMPLES = "'own_questions', 'skill_set_only'"


def upgrade() -> None:
    op.drop_constraint(op.f(_REASON), _TABLE, type_="check")
    op.create_check_constraint(
        op.f(_REASON),
        _TABLE,
        f"unknown_reason IS NULL OR unknown_reason IN ({_REASONS}, {_NEW_REASONS})",
    )
    op.drop_constraint(op.f(_SAMPLE), _TABLE, type_="check")
    op.create_check_constraint(
        op.f(_SAMPLE), _TABLE, f"sample IS NULL OR sample IN ({_SAMPLES}, 'own_not_asked')"
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE {_TABLE} SET unknown_reason = 'failed' WHERE unknown_reason IN ({_NEW_REASONS})"
    )
    op.execute(f"UPDATE {_TABLE} SET sample = 'own_questions' WHERE sample = 'own_not_asked'")
    op.drop_constraint(op.f(_REASON), _TABLE, type_="check")
    op.create_check_constraint(
        op.f(_REASON), _TABLE, f"unknown_reason IS NULL OR unknown_reason IN ({_REASONS})"
    )
    op.drop_constraint(op.f(_SAMPLE), _TABLE, type_="check")
    op.create_check_constraint(op.f(_SAMPLE), _TABLE, f"sample IS NULL OR sample IN ({_SAMPLES})")
