"""Keep a routine's run provenance after the routine itself is deleted.

The reporting FK intentionally becomes null on deletion. Reusing it for runtime
authorization would therefore release a parked run's guard precisely when its
owner stopped the routine. This immutable origin is not a FK and grants nothing:
the guard still requires the live row and the creator's current access.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0260_routine_run_origin"
down_revision: str | None = "0259_trigger_version_pin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("routine_origin_id", sa.UUID(), nullable=True))
    op.execute("UPDATE agent_runs SET routine_origin_id = trigger_id WHERE trigger_id IS NOT NULL")


def downgrade() -> None:
    op.drop_column("agent_runs", "routine_origin_id")
