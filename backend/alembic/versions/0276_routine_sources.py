"""Bind recurring work to reviewed sources across activations.

Existing routines require source review; no migration grants account or tool
authority. Drain old workers and update API/workers together before resuming.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0276_routine_sources"
down_revision: str | None = "0275_routine_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers", sa.Column("approved_sources", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "approved_sources")
