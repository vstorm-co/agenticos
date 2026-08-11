"""Agent trigger name - a human title, shown instead of the agent's name

Revision ID: 0024_agent_trigger_name
Revises: 0023_agent_event_triggers
Create Date: 2026-08-11

A trigger has always been listed by the agent it fires, so two schedules on one
agent read identically. This adds an optional `name`: a human title shown wherever
a trigger is listed away from its form, falling back to the agent's name when
unset. Nullable and with no backfill on purpose - an existing row keeps rendering
the agent name, and a "just schedule it" without a title reads the same, so the
column adds a label without forcing one.
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_agent_trigger_name"
down_revision = "0023_agent_event_triggers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_triggers", sa.Column("name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_triggers", "name")
