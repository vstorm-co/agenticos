"""The index every read of a user's sessions actually wants (#1256).

All three of them ask the same question - this user's sessions, most recently
used first: the devices list, its page count, and the admin drawer's last-seen.
The table had an index on `user_id` alone, so answering meant fetching a user's
rows and sorting them.

That is fine for a week-old account and not for a year-old one. Nothing prunes
`sessions`: a refresh deactivates the row it used and inserts another, so the
history grows for as long as somebody keeps signing in, and the admin drawer got
slower for exactly the accounts an administrator is most likely to open.

`id` is in the index because `last_used_at` ties on two sign-ins in the same
moment and the page order has to be total - the same reason the query orders on
it.

The single-column index goes: this one leads on `user_id`, so Postgres would
never choose it and every insert would still maintain it.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0061_session_last_used_index"
down_revision: str | None = "0060_conversation_favourites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPOSITE = "sessions_user_id_last_used_at_idx"
_SINGLE = "sessions_user_id_idx"


def upgrade() -> None:
    # `text(...)` for the descending column: a plain string would be quoted as
    # one identifier named "last_used_at DESC".
    op.create_index(_COMPOSITE, "sessions", ["user_id", text("last_used_at DESC"), "id"])
    op.drop_index(_SINGLE, table_name="sessions")


def downgrade() -> None:
    op.create_index(_SINGLE, "sessions", ["user_id"], unique=False)
    op.drop_index(_COMPOSITE, table_name="sessions")
