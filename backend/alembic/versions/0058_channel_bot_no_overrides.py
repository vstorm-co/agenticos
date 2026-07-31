"""Drop the channel bot's assistant-era override columns

Revision ID: 0058_channel_bot_no_overrides
Revises: 0057_notification_prefs
Create Date: 2026-07-30

`ai_model_override` and `system_prompt_override` configured the template's
general assistant, which answered any channel message that mentioned no agent.
That assistant is gone: a bot only ever relays to published agents resolved
through agent_exposures, and an agent's model and instructions live in its
spec, where publishing validates them. Columns that configure nothing would
otherwise sit in the schema promising behaviour the router no longer has.

The downgrade restores the columns but not their contents - what they held
configured code that no longer exists, so there is nothing faithful to restore.
"""

import sqlalchemy as sa

from alembic import op

revision = "0058_channel_bot_no_overrides"
down_revision = "0057_notification_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("channel_bots", "ai_model_override")
    op.drop_column("channel_bots", "system_prompt_override")


def downgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column("ai_model_override", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "channel_bots",
        sa.Column("system_prompt_override", sa.Text(), nullable=True),
    )
