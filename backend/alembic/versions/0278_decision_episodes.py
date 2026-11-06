"""Keep structured decision evidence on the existing scoped memory ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0278_decision_episodes"
down_revision: str | None = "0277_project_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory_claims", sa.Column("episode", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_claims", "episode")
