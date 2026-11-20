"""Track room thread lifecycle, following, and read cursors."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0350_room_thread_state"
down_revision: str | None = "0349_room_message_reactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "room_threads",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("closed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "organization_id", "conversation_id", "root_message_id", name="room_threads_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_thread_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "root_message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_room_thread_root",
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="room_threads_closed_by_user_id_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="room_threads_archived_by_user_id_fkey",
        ),
        sa.CheckConstraint(
            "state IN ('open', 'closed', 'archived')",
            name=op.f("room_threads_ck_room_thread_state_check"),
        ),
        sa.CheckConstraint(
            "closed_by_user_id IS NULL OR closed_at IS NOT NULL",
            name=op.f("room_threads_ck_room_thread_closed_actor_time_check"),
        ),
        sa.CheckConstraint(
            "archived_by_user_id IS NULL OR archived_at IS NOT NULL",
            name=op.f("room_threads_ck_room_thread_archived_actor_time_check"),
        ),
    )
    op.create_index(
        "ix_room_threads_conversation_state",
        "room_threads",
        ["organization_id", "conversation_id", "state"],
    )

    op.create_table(
        "room_thread_follows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("following", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="room_thread_follows_pkey"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id", "root_message_id"],
            [
                "room_threads.organization_id",
                "room_threads.conversation_id",
                "room_threads.root_message_id",
            ],
            ondelete="CASCADE",
            name="fk_room_thread_follow_thread",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_thread_follow_member",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_id",
            "root_message_id",
            "user_id",
            name="uq_room_thread_follow_user",
        ),
    )
    op.create_index(
        "ix_room_thread_follows_user",
        "room_thread_follows",
        ["organization_id", "user_id", "following"],
    )

    op.create_table(
        "room_thread_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_read_ordinal", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="room_thread_reads_pkey"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id", "root_message_id"],
            [
                "room_threads.organization_id",
                "room_threads.conversation_id",
                "room_threads.root_message_id",
            ],
            ondelete="CASCADE",
            name="fk_room_thread_read_thread",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_thread_read_member",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "conversation_id",
            "root_message_id",
            "user_id",
            name="uq_room_thread_read_user",
        ),
        sa.CheckConstraint(
            "last_read_ordinal >= 0",
            name=op.f("room_thread_reads_ck_room_thread_read_ordinal_check"),
        ),
    )
    op.create_index(
        "ix_room_thread_reads_user",
        "room_thread_reads",
        ["organization_id", "user_id", "conversation_id"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE room_threads, room_thread_follows, room_thread_reads IN ACCESS EXCLUSIVE MODE"
    )
    used = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM room_threads) OR "
            "EXISTS (SELECT 1 FROM room_thread_follows) OR "
            "EXISTS (SELECT 1 FROM room_thread_reads)"
        )
    )
    if used:
        raise RuntimeError("Cannot discard room thread state, follows or read cursors")
    op.drop_index("ix_room_thread_reads_user", table_name="room_thread_reads")
    op.drop_table("room_thread_reads")
    op.drop_index("ix_room_thread_follows_user", table_name="room_thread_follows")
    op.drop_table("room_thread_follows")
    op.drop_index("ix_room_threads_conversation_state", table_name="room_threads")
    op.drop_table("room_threads")
