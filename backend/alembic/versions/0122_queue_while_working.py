"""Let each person choose whether a message sent mid-run joins it or waits (#2087).

`users.queue_while_working` is false for everybody, which keeps the default the
console now has: a message typed while the agent works reaches the running turn
at its next step. True puts it in the queue for after the turn instead.

Revision ID: 0122_queue_while_working
Revises: 0121_trigger_runs_as_creator
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0122_queue_while_working"
down_revision: str | None = "0121_trigger_runs_as_creator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("queue_while_working", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "queue_while_working")
