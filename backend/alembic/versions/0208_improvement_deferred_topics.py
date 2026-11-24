"""Keep the knowledge documents a person set aside in an improvement session.

Revision ID: 0208_improvement_deferred
Revises: 0207_improvement_triage
Existing sessions set nothing aside.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0208_improvement_deferred"
down_revision: str | None = "0207_improvement_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "improvement_runs",
        sa.Column(
            "deferred_topic_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("improvement_runs", "deferred_topic_ids")
