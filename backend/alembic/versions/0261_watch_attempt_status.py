"""Separate failed watch attempts from successful readings without inventing history.

The previous timestamp included unsuccessful model calls. Preserve it as legacy
history rather than guessing which past check succeeded. New attempts carry an
explicit state and only a completed reading advances last_run_at.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0261_watch_attempt_status"
down_revision: str | None = "0260_routine_run_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "watches", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("watches", sa.Column("last_attempt_status", sa.String(32), nullable=True))
    op.create_check_constraint(
        "ck_watch_attempt_status",
        "watches",
        "(last_attempt_at IS NULL AND last_attempt_status IS NULL) OR "
        "(last_attempt_at IS NOT NULL AND last_attempt_status IS NOT NULL AND "
        "last_attempt_status IN ('completed', 'source_unavailable', 'access_revoked', 'not_completed'))",
    )


def downgrade() -> None:
    op.drop_constraint("ck_watch_attempt_status", "watches", type_="check")
    op.drop_column("watches", "last_attempt_status")
    op.drop_column("watches", "last_attempt_at")
