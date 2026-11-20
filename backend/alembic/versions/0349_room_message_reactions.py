"""Persist human emoji reactions on shared conversation messages."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0349_room_message_reactions"
down_revision: str | None = "0348_room_mention_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_message_reactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("emoji", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_room_message_reaction_organization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_message_reaction_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_room_message_reaction_message",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_message_reaction_member",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_id",
            "message_id",
            "user_id",
            "emoji",
            name="uq_room_message_reaction_user_emoji",
        ),
        sa.CheckConstraint(
            "char_length(emoji) BETWEEN 1 AND 32",
            name="ck_room_message_reaction_emoji_length",
        ),
    )
    op.create_index(
        "ix_room_message_reactions_message",
        "room_message_reactions",
        ["organization_id", "conversation_id", "message_id"],
    )


def downgrade() -> None:
    has_reactions = bool(
        op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM room_message_reactions)"))
    )
    if has_reactions:
        raise RuntimeError(
            "room message reaction evidence exists; export or remove it before downgrade"
        )
    op.drop_index("ix_room_message_reactions_message", table_name="room_message_reactions")
    op.drop_table("room_message_reactions")
