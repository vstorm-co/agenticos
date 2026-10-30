"""A trigger that works on its creator's own computer (#2305).

`agent_triggers.local_target` names a folder on the creator's computer and the
mode a fire works there in, carried out by their desktop app. Null - every
existing row - keeps the agent's own sandbox.

Revision ID: 0174_trigger_local_target
Revises: 0173_apns
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0174_trigger_local_target"
down_revision: str | None = "0173_apns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("local_target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "local_target")
