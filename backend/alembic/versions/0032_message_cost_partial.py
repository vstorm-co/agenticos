"""Whether a message's recorded cost is a floor rather than the whole of it.

`messages` has carried `input_tokens`, `output_tokens` and `cost_usd` since the
transcript learned to show what an answer cost. What it could not say is that the
number is short: when a run reaches a model `genai-prices` has no entry for, the
ledger books the request with `cost_usd = 0` and `priced = False`, and the run row
records that as `cost_is_partial`. The message recorded only the total, so an
answer whose real cost is unknown rendered identically to one measured exactly.

Nullable, and null means **not recorded** rather than "exact": every message
written before this column has no answer, and inventing `false` for them would
claim a precision nobody measured. A client draws the caveat on `true` alone.

Revision ID: 0032_message_cost_partial
Revises: 0031_profile_context_length
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_message_cost_partial"
down_revision: str | None = "0031_profile_context_length"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("cost_is_partial", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "cost_is_partial")
