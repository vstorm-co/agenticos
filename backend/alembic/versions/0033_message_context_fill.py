"""How many tokens the history sent with a turn occupied.

The reading existed only on the live `complete` frame, so it was on screen for
as long as the tab was: reload the chat and the gauge was gone. That is the one
moment somebody asks "how close am I to the ceiling before I send the next
message" — the same reason `cost_usd` stopped living only in that frame.

**Only the tokens, deliberately.** How much history there is is a fact about the
conversation and survives a model change; the *window* it is a share of is a fact
about the model answering next, and the chat lets somebody switch that between
turns. Stored together, a 500,000-token history measured on a 1M-context model
would go on reading "50%" after a switch to a 128K one, where it is really 390%
and the next request is refused outright — a number that lies in the one
direction that costs a run. So the share is resolved where the model is known,
and only this half is written down.

Null means not recorded: every message written before this, and any turn that
never reached a model.

Revision ID: 0033_message_context_fill
Revises: 0032_message_cost_partial
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_message_context_fill"
down_revision: str | None = "0032_message_cost_partial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("context_used_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "context_used_tokens")
