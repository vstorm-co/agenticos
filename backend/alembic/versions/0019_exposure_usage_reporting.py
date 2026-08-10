"""How talkative an agent is about cost, on the binding rather than on the bot.

It sat on `channel_bots`, which made it a property of the chat platform: an
operator with `channels:manage` set it, and it appeared in a table of servers
and tokens next to nothing else about the agent. But what a turn cost is
something the *agent's* author decides alongside the rest of what that agent
says on that surface - beside `prompt`, `session_scope` and `tools`, which are
all on the binding for exactly this reason.

Nothing was ambiguous about the move once a bot served one agent (`0018`); until
then the two were genuinely different questions. Existing values are copied
across, so no bot changes how it behaves, and the column on `channel_bots` is
dropped in the same migration - two homes for one setting is how they come to
disagree.

Revision ID: 0019_exposure_usage_reporting
Revises: 0018_one_agent_per_bot
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_exposure_usage_reporting"
down_revision: str | Sequence[str] | None = "0018_one_agent_per_bot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same literal `app/services/channels/base.py` holds, spelled out because a
# migration must not import application code - the module it lives in changes,
# and a migration that ran once has to keep meaning what it meant.
_DEFAULT = '{"mode": "near_limit", "near_limit_percent": 80, "every_n": 10}'


def upgrade() -> None:
    op.add_column(
        "agent_exposures",
        sa.Column(
            "usage_reporting",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT}'::jsonb"),
        ),
    )
    # Whatever each bot was set to, onto the binding it serves. A bot with no
    # binding has nothing to copy to, and its setting was governing nothing.
    op.execute(
        """
        UPDATE agent_exposures AS e
        SET usage_reporting = b.usage_reporting::jsonb
        FROM channel_bots AS b
        WHERE b.id = e.channel_bot_id AND b.usage_reporting IS NOT NULL
        """
    )
    op.drop_column("channel_bots", "usage_reporting")


def downgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column(
            "usage_reporting",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT}'"),
        ),
    )
    op.execute(
        """
        UPDATE channel_bots AS b
        SET usage_reporting = e.usage_reporting
        FROM agent_exposures AS e
        WHERE e.channel_bot_id = b.id
        """
    )
    op.drop_column("agent_exposures", "usage_reporting")
