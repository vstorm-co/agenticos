"""Drop the per-session triage of an improvement session's examples.

Revision ID: 0210_improvement_drop_triage
Revises: 0209_knowledge_draft_askers
A session's rounds run without waiting for a person, so an example ignored on
the Understand step had already shaped the attempts; every round now reads every
example. A downgrade brings the column back empty, which reads as no decisions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0210_improvement_drop_triage"
down_revision: str | None = "0209_knowledge_draft_askers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("improvement_runs", "evidence_decisions")


def downgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column(
            "evidence_decisions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
