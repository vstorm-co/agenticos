"""Normalise the mixed `channel_sessions.chat_type` vocabulary to two words.

Telegram used to persist its own `supergroup` and `channel` while Slack and
Mattermost collapsed everything but a DM to `group`, so the column held a
different vocabulary per platform. The adapters now all emit `private` or
`group` (#556); this folds the rows written before that so a consumer reading
`chat_type == "group"` sees every room, not only the ones Slack and Mattermost
wrote. Every value that is not `private` was a room, which is exactly the reading
the one live consumer already took (`!= "private"`), so no row changes meaning.

Revision ID: 0076_normalize_channel_chat_type
Revises: 0075_user_credential_version
Create Date: 2026-09-11

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0076_normalize_channel_chat_type"
down_revision: str | None = "0075_user_credential_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE channel_sessions SET chat_type = 'group' "
        "WHERE chat_type NOT IN ('private', 'group')"
    )


def downgrade() -> None:
    # Irreversible: the platform distinction between `supergroup`, `channel` and a
    # plain `group` was folded away and the row no longer carries which it was.
    pass
