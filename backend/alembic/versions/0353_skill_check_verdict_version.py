"""Mark the rule that judged each skill-check agent.

Empty families and an inconclusive result are valid current outcomes, so they
cannot identify historical results. Existing rows start at zero; a successful
judgement records the current version and is not repeatedly swept.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0353_skill_check_verdict_version"
down_revision: str = "0352_eval_answer_gaps"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "skill_check_agents",
        sa.Column("verdict_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("skill_check_agents", "verdict_version")
