"""Trigger fire-in-flight marker - closing the self-overlap window

Revision ID: 0048_trigger_fire_in_flight
Revises: 0047_trigger_webhook_target
Create Date: 2026-08-12

The heartbeat's no-overlap guard reads `last_run_id`, but the fired run writes it
only when `execute` returns - so while a run executes, `last_run_id` still names
the previous (terminal) run, and a run slower than its interval fires on top of
itself (agenticos#588). This adds `fire_in_flight_since`: the claim sets it in the
same UPDATE that advances `next_fire_at`, so there is no gap; the fired run clears
it in a `finally`. `claim_due` skips a trigger whose marker is set and younger than
a lease, so a child that died without clearing un-wedges itself rather than parking
the schedule for ever.

Nullable, no backfill: an idle trigger has no fire in flight, so a null is the
right resting state for every existing row.
"""

import sqlalchemy as sa

from alembic import op

revision = "0048_trigger_fire_in_flight"
down_revision = "0047_trigger_webhook_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_triggers",
        sa.Column("fire_in_flight_since", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_triggers", "fire_in_flight_since")
