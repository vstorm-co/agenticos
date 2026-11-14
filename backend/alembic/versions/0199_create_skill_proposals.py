"""Allow proposals that create and bind a skill after a human accepts.

Revision ID: 0199_create_skill_proposals
Revises: 0198_review_reevaluation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0199_create_skill_proposals"
down_revision: str | None = "0198_review_reevaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(values: str) -> None:
    op.drop_constraint("ck_spec_proposal_hunk_kind", "spec_proposal_hunks", type_="check")
    op.create_check_constraint(
        "ck_spec_proposal_hunk_kind", "spec_proposal_hunks", f"kind IN ({values})"
    )


def upgrade() -> None:
    _check("'instructions', 'tool_override', 'spec_field', 'create_skill'")


def downgrade() -> None:
    op.execute("DELETE FROM spec_proposal_hunks WHERE kind = 'create_skill'")
    _check("'instructions', 'tool_override', 'spec_field'")
