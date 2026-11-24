"""Store personal message bookmarks without copying transcript text.

A pin belongs to the reader, not to a shared conversation. It keeps only the
reader, conversation and message ids; previews are projected from the live
message when the authorized reader lists their pins. The composite foreign key
ensures a pin cannot name a message from a different conversation and removes
the bookmark when that message is deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0337_conversation_message_pins"
down_revision: str | None = "0336_merge_core_v1761"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_message_pins",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_conversation_message_pin_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("conversation_message_pins_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "conversation_id",
            "message_id",
            name=op.f("conversation_message_pins_pkey"),
        ),
    )
    op.create_index(
        "conversation_message_pins_user_conversation_created_at_idx",
        "conversation_message_pins",
        ["user_id", "conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "conversation_message_pins_conversation_message_idx",
        "conversation_message_pins",
        ["conversation_id", "message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "conversation_message_pins_conversation_message_idx",
        table_name="conversation_message_pins",
    )
    op.drop_index(
        "conversation_message_pins_user_conversation_created_at_idx",
        table_name="conversation_message_pins",
    )
    op.drop_table("conversation_message_pins")
