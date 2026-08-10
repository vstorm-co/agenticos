"""What the agent may look up on *this* bot.

An organization can bind one agent to two Mattermost servers and three Slack
workspaces, and "may this agent list the members of the channel it is in" has a
different answer on each of them - the internal Mattermost is not the customer
Slack. A switch in the agent spec has exactly one answer for all five, so this
is a column on the binding, beside `prompt` and `session_scope`, which are on
the binding for the same reason.

A list of tool ids from `app.agents.capabilities.channel_tools` rather than a
boolean: reading who is in a channel and reading what they said in it are two
decisions, and the empty list - which is what every existing binding gets - is
the one that changes nothing.

Revision ID: 0017_exposure_tools
Revises: 0016_seed_exposure_prompts
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_exposure_tools"
down_revision: str | Sequence[str] | None = "0016_seed_exposure_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_exposures",
        sa.Column(
            "tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            # Not nullable: "nobody has chosen yet" and "nothing is granted" are
            # the same state here, and a NULL would give every reader a third
            # case to handle for no gain.
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_exposures", "tools")
