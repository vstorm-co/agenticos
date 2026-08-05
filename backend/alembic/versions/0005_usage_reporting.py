"""What a bot says about what a turn cost

Revision ID: 0005_usage_reporting
Revises: 0004_skill_proposals
Create Date: 2026-08-03

A bot that stops answering because its organization hit a monthly cap looks
broken, and the only difference between "broken" and "out of budget" is somebody
having said so beforehand. So a bot can report what a turn spent - tokens, cost,
how much of the month is gone, and how full the workspace behind it is.

`channel_bots.usage_reporting` is when it says that out loud: `off` records it and
stays quiet, `always` reports every turn, `near_limit` reports once something
passes a threshold, `every_n` reports every n-th turn of a chat. Its own column
rather than a key in `access_policy`, which decides who may talk to the bot - one
JSON blob holding both would put "how noisy is it" next to "who is allowed in",
and the next person narrowing access would be editing the same value as the person
tuning noise.

`channel_sessions.turn_count` is what `every_n` counts. In a column rather than by
counting rows in `messages`, because the answer is needed on every turn and a
`COUNT(*)` on a table that grows forever is a cost that only goes up. It is
incremented by the `UPDATE` that already records the chat's activity, so it is
free.

Existing rows get the same default a new bot gets - `near_limit` rather than `off`,
because defaulting to silence would leave every already-registered bot in exactly
the state this exists to prevent.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_usage_reporting"
down_revision = "0004_skill_proposals"
branch_labels = None
depends_on = None

_DEFAULT = '{"mode": "near_limit", "near_limit_percent": 80, "every_n": 10}'


def upgrade() -> None:
    op.add_column(
        "channel_bots",
        sa.Column(
            "usage_reporting",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(f"'{_DEFAULT}'"),
        ),
    )
    op.add_column(
        "channel_sessions",
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channel_sessions", "turn_count")
    op.drop_column("channel_bots", "usage_reporting")
