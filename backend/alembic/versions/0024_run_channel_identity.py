"""Which chat account a channel run came from.

A run records who it ran *as* in `user_id`, and until now that was also the only
answer to "who asked". In a group chat those are different questions: the turn
runs as the binding's creator, while the person who typed it is a chat account
that may have no platform user behind it at all (#639).

`channel_sessions` cannot answer it either - one row per bot and chat, so its
`identity_id` is whoever opened the conversation, not whoever spoke this turn.
In a channel with four people that names one of them.

`SET NULL`, in step with `user_id` and `exposure_id` on this table: deleting a
chat identity must not delete the record of what it spent.

No backfill, and none is possible: every run before this revision was made by a
linked account, which `user_id` already names.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0024_run_channel_identity"
down_revision: str | Sequence[str] | None = "0023_embed_kinds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("channel_identity_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "agent_runs_channel_identity_id_fkey",
        "agent_runs",
        "channel_identities",
        ["channel_identity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_runs_channel_identity_id",
        "agent_runs",
        ["channel_identity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_channel_identity_id", table_name="agent_runs")
    op.drop_constraint("agent_runs_channel_identity_id_fkey", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "channel_identity_id")
