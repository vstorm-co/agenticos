"""A schedule is read in a time zone (#2195).

A cron expression was evaluated in UTC, so somebody in Warsaw wanting "daily at
09:00" wrote 07:00 in summer and 08:00 in winter, and the run moved an hour twice
a year. `time_zone` holds the IANA zone the expression means; existing rows are
left null, which keeps reading them in UTC exactly as before.

Revision ID: 0176_trigger_time_zone
Revises: 0175_outlook_event_source
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0176_trigger_time_zone"
down_revision: str | None = "0175_outlook_event_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_triggers", sa.Column("time_zone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_triggers", "time_zone")
