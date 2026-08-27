"""A favourite conversation belongs to the reader, not to the thread.

A conversation can be shared, and a channel thread has participants rather than
an owner - so `is_favourite` as a boolean on `conversations` would let one
person's star decide where the thread sits for everybody who can see it. A row
per `(user_id, conversation_id)` is what makes it the reader's (#929).

Both foreign keys cascade. A deleted account leaves no stars behind and a
deleted conversation cannot be starred by anybody, so nothing here outlives what
it points at.

The pair is the primary key: starring twice is a conflict rather than a second
row, and the index the sidebar's listing needs - this reader's favourites - is
the key's own. The second index is for the other direction, which the delete of
a conversation walks.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060_conversation_favourites"
down_revision: str | None = "0059_invite_fk_ondelete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_favourites",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("conversation_favourites_conversation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("conversation_favourites_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "conversation_id", name=op.f("conversation_favourites_pkey")
        ),
    )
    op.create_index(
        op.f("conversation_favourites_conversation_id_idx"),
        "conversation_favourites",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("conversation_favourites_conversation_id_idx"),
        table_name="conversation_favourites",
    )
    op.drop_table("conversation_favourites")
