"""Keep a person's triage of an improvement session's evidence.

Revision ID: 0207_improvement_triage
Revises: 0206_improvement_publication
Existing sessions start with no decisions, which reads as the classifier's own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0207_improvement_triage"
down_revision: str | None = "0206_improvement_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column(
            "evidence_decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("improvement_runs", "evidence_decisions")
