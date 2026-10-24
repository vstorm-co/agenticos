"""Stamp table events on the trigger activation clock, after acquiring its lock.

Revision ID: 0221_table_event_wall_clock
Revises: 0220_workflow_retained_spend
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0221_table_event_wall_clock"
down_revision: str | None = "0220_workflow_retained_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "virtual_table_outbox", "created_at", server_default=sa.text("clock_timestamp()")
    )


def downgrade() -> None:
    op.alter_column("virtual_table_outbox", "created_at", server_default=sa.text("now()"))
