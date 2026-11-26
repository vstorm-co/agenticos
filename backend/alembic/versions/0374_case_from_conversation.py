"""Record on each dataset case whether it was written from a conversation.

A case taken from a chat is masked for readers who may not open that chat. Its
run, conversation and message links are `SET NULL`, so once the chat is deleted a
case drafted from it by Generate cases (`source = synthetic`) kept nothing saying
where it came from, and every reader of the dataset saw its text. A copied case
(`source = conversation`) stayed masked only because of its source.

The flag is set when a case is written with any of those links or a recorded
person, and carried to every later revision. The backfill marks every revision
that has a link, a conversation source, or a recorded asker, note author or
history author: each is only ever taken from a chat, and outlives the
conversation. A generated case whose chat was deleted before this revision, from
an anonymous visitor's conversation, has none of these left and cannot be
recovered.

Downgrade drops the column; the code before this revision masks on the source and
the conversation link, as it did.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0374_case_from_conversation"
down_revision: str | None = "0373_project_filesystem_mounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dataset_cases",
        sa.Column("from_conversation", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(
        "UPDATE dataset_cases SET from_conversation = true "
        "WHERE source = 'conversation' "
        "OR source_run_id IS NOT NULL "
        "OR source_conversation_id IS NOT NULL "
        "OR source_message_id IS NOT NULL "
        "OR asked_by_user_id IS NOT NULL "
        "OR noted_by_user_id IS NOT NULL "
        "OR EXISTS (SELECT 1 FROM unnest(history_author_ids) AS author WHERE author IS NOT NULL)"
    )


def downgrade() -> None:
    op.drop_column("dataset_cases", "from_conversation")
