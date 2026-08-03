"""What a turn cost, on the message it cost it on

Revision ID: 0006_message_usage
Revises: 0005_usage_reporting
Create Date: 2026-08-03

A turn's cost lived only in the `complete` frame on the WebSocket, so it existed
for exactly as long as the tab did. Reopening a conversation showed no cost at
all - not under the input, not under any message - and the numbers came back only
after sending something new. "What did that answer cost" is a question asked
*afterwards*, which is precisely when the answer had been thrown away.

`messages.tokens_used` already existed and is not enough: one total, no split
between input and output, no money. Input and output are priced an order of
magnitude apart, so a single figure cannot say whether a turn was expensive
because of a long context or a long answer - and cost is the column somebody
watching a budget actually reads.

Nullable, with no backfill. Every message written before this migration was
measured and the measurement is gone; `agent_runs` holds the run's totals but
nothing links a run to the message it produced, so any pairing would be a guess
at which run wrote which row. Null means "not recorded", which is true, and the
client draws nothing rather than zeroes - "$0.0000" under an answer that cost
money is worse than saying nothing.

`Numeric(12, 6)` to match `agent_runs.cost_usd` and `organizations.monthly_budget_usd`.
A float here would make a sum of a thousand turns disagree with the budget it is
compared against.
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_message_usage"
down_revision = "0005_usage_reporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "cost_usd")
    op.drop_column("messages", "output_tokens")
    op.drop_column("messages", "input_tokens")
