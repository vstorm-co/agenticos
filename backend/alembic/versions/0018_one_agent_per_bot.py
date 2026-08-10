"""One agent per bot, not several behind one handle.

A bot user is one identity in the chat. On Mattermost every reply arrives from
the same avatar and the same name whichever agent produced it, so serving
several behind one bot meant somebody in a channel had to type a slug to pick
between agents they could not see - and a message that named none was answered
with a list of handles rather than an answer.

Replaces `uq_exposure_agent_bot`, which allowed that: unique on the bot alone is
strictly stronger, and makes the pair unique as a consequence.

The upgrade fails on a deployment where a bot already serves two agents. That is
the honest outcome - the second binding is a decision somebody made and only they
can say which agent keeps the bot - and the failure names the bot.

Revision ID: 0018_one_agent_per_bot
Revises: 0017_exposure_tools
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_one_agent_per_bot"
down_revision: str | Sequence[str] | None = "0017_exposure_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_exposure_agent_bot", "agent_exposures", type_="unique")
    op.create_unique_constraint("uq_exposure_bot", "agent_exposures", ["channel_bot_id"])


def downgrade() -> None:
    op.drop_constraint("uq_exposure_bot", "agent_exposures", type_="unique")
    op.create_unique_constraint(
        "uq_exposure_agent_bot", "agent_exposures", ["agent_id", "channel_bot_id"]
    )
