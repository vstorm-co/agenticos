"""Choose the model new judges grade on, and let a run measure how steady grading is.

Revision ID: 0213_grading_model
Revises: 0212_improvement_waiting
An organization may name the model its new judges run on; with none, a new judge
takes one that costs more than the agent it grades. A `stability` eval run asks
every question again, to show before an improvement starts whether its answers
and their grading hold still.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0213_grading_model"
down_revision: str | None = "0212_improvement_waiting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PURPOSE = "eval_runs_ck_eval_run_purpose_check"


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("grading_model_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "organizations_grading_model_profile_id_fkey",
        "organizations",
        "model_profiles",
        ["grading_model_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f(_PURPOSE), "eval_runs", type_="check")
    op.create_check_constraint(
        op.f(_PURPOSE), "eval_runs", "purpose IN ('manual', 'gate', 'stability')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM eval_runs WHERE purpose = 'stability'")
    op.drop_constraint(op.f(_PURPOSE), "eval_runs", type_="check")
    op.create_check_constraint(op.f(_PURPOSE), "eval_runs", "purpose IN ('manual', 'gate')")
    op.drop_constraint(
        "organizations_grading_model_profile_id_fkey", "organizations", type_="foreignkey"
    )
    op.drop_column("organizations", "grading_model_profile_id")
