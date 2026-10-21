"""Voice calls: an index under every column a lookup or a parent's delete filters on (#54).

`0155_voice_calls` indexed only the organization's minutes, the sweep's
heartbeat, the run and the user. Three things read `voice_calls` by another
column, and each scanned the table:

- the embed's open-call count, taken under that embed's advisory lock on every
  visitor's start, so a scan there serialises visitors' starts behind it;
- Activity's walk down a call's reconnects, by `resume_of`;
- the `ON DELETE SET NULL` of each parent - an agent, a conversation, an embed,
  a key, and a connection a reconnect continued - which finds its rows by the
  column.

Plain btree indexes, whole rather than partial: a partial index on open calls
would serve the embed's count but not an embed's delete, which must find every
call it ever had. The table is new in this release, so building them is cheap
and needs no `CONCURRENTLY`.

Revision ID: 0157_voice_call_indexes
Revises: 0156_message_voice_turns
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0157_voice_call_indexes"
down_revision: str | None = "0156_message_voice_turns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("agent_id", "conversation_id", "embed_id", "secret_id", "resume_of")


def upgrade() -> None:
    for column in _COLUMNS:
        op.create_index(op.f(f"voice_calls_{column}_idx"), "voice_calls", [column], unique=False)


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_index(op.f(f"voice_calls_{column}_idx"), table_name="voice_calls")
