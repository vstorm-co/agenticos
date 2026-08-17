"""How far a conversation's system-reminders cadence has advanced.

A system reminder re-states guidance every N model requests to counter
instruction fade in a long session. The request counter it fires on lives only
as long as the run that made the requests, so between turns it reset to zero -
and a reminder set to fire "every 10 requests" never fired at all in a chat of
ten one-request turns.

So the cadence is written down. `reminder_state` holds the per-request counter and
the per-reminder fire counts as one JSONB blob; the next turn seeds from it and
writes it back, so leaving and reloading a conversation resumes the cadence rather
than restarting it. The reminder text is never stored - it is injected ephemerally
per request and never enters the transcript. Only the counters are durable.

Null until a system-reminders capability has fired once, which for a conversation
whose agent has none is for ever.

Revision ID: 0036_conversation_reminder_state
Revises: 0035_avatar_color
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036_conversation_reminder_state"
down_revision: str | None = "0035_avatar_color"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("reminder_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "reminder_state")
