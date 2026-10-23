"""Case generations: count the drafted cases left out of the proposals.

A generation records what it proposed; what it left out was only logged. Two
counts make that visible to the person who asked: `unreadable_count`, cases the
generator wrote in a shape that could not be read, and `rejected_count`,
readable cases that did not keep to what the generator was shown. Both start at
zero for the generations already recorded, which is what nobody knew about them.

Revision ID: 0179_case_generation_drop_counts
Revises: 0180_improvement_sessions
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0179_case_generation_drop_counts"
down_revision: str | None = "0180_improvement_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "case_generations_ck_case_generation_counts_check"
_COUNTS = "proposed_count >= 0 AND accepted_count >= 0 AND dismissed_count >= 0"


def upgrade() -> None:
    for column in ("unreadable_count", "rejected_count"):
        op.add_column(
            "case_generations",
            sa.Column(column, sa.Integer(), server_default="0", nullable=False),
        )
    op.drop_constraint(op.f(_CHECK), "case_generations", type_="check")
    op.create_check_constraint(
        op.f(_CHECK),
        "case_generations",
        f"{_COUNTS} AND unreadable_count >= 0 AND rejected_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(op.f(_CHECK), "case_generations", type_="check")
    op.create_check_constraint(op.f(_CHECK), "case_generations", _COUNTS)
    op.drop_column("case_generations", "rejected_count")
    op.drop_column("case_generations", "unreadable_count")
