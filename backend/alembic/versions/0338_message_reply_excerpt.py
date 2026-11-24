"""Persist a person's selected excerpt with the reply link.

The excerpt is a bounded, normalized selection from the linked source message.
It preserves the words the reply answers without duplicating or altering the
message body.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0338_message_reply_excerpt"
down_revision: str | None = "0337_conversation_message_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("reply_to_excerpt", sa.String(length=280), nullable=True))
    op.create_check_constraint(
        op.f("messages_reply_excerpt_requires_message_check"),
        "messages",
        "reply_to_excerpt IS NULL OR reply_to_message_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("messages_reply_excerpt_requires_message_check"), "messages", type_="check"
    )
    op.drop_column("messages", "reply_to_excerpt")
