"""Drop the per-person choice of queueing a message sent mid-run (#2087).

The console now always holds a message typed while the agent works until the
answer, and each queued message can be sent into the running task on its own -
so the account-wide switch `0122_queue_while_working` added has nothing left to
decide. Channels keep their own behaviour, which never read it.

Revision ID: 0126_drop_queue_while_working
Revises: 0125_conversation_origin
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0126_drop_queue_while_working"
down_revision: str | None = "0125_conversation_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "queue_while_working")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("queue_while_working", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
