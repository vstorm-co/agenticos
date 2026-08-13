"""Who wrote a message, when the writer was a chat account.

A channel thread is one conversation with several people in it, and `messages`
recorded none of them: a room where four people spoke was stored as an
undifferentiated sequence of `user` and `assistant` rows. That was invisible
while a thread belonged to whoever opened it and only they could read it. It
stops being invisible the moment a thread is shown to everybody who spoke in it,
because four turns reading "hej" with no author is not a conversation.

So the same column `agent_runs` gained in `0024`, on the row that holds the text.
It answers two questions with one value: who wrote this turn, and - as a
`DISTINCT` over the thread - who has spoken in it, which is what decides whose
conversation list it appears in. A second table listing participants would be
the same set, denormalised, with a way to disagree with the messages.

Null on every assistant turn and on anything typed into the dashboard, which is
the honest value: neither has a chat account behind it.

`SET NULL`, in step with `agent_runs.channel_identity_id`: deleting a chat
identity must not delete what was said.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0026_message_author"
down_revision: str | Sequence[str] | None = "0025_embed_page_logo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("channel_identity_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "messages_channel_identity_id_fkey",
        "messages",
        "channel_identities",
        ["channel_identity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Read two ways, and the index serves both: every message of one thread with
    # its author, and "which threads has this account spoken in" when a listing
    # asks on behalf of a person who has just linked one.
    op.create_index(
        "messages_channel_identity_id_idx",
        "messages",
        ["channel_identity_id"],
    )


def downgrade() -> None:
    op.drop_index("messages_channel_identity_id_idx", table_name="messages")
    op.drop_constraint("messages_channel_identity_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "channel_identity_id")
