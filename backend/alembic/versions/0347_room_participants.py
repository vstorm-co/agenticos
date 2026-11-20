"""Add explicit human and agent rosters for private and public chat rooms.

Existing conversations remain legacy chats until someone adds a participant or
creates a room. Room membership is tenant-scoped, and project conversations keep
their existing project access rules.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0347_room_participants"
down_revision: str | None = "0346_merge_t3_v1850"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("room_visibility", sa.String(16), nullable=True))
    op.create_check_constraint(
        op.f("conversations_ck_conversation_room_visibility_check"),
        "conversations",
        "room_visibility IS NULL OR room_visibility IN ('private', 'public')",
    )
    op.create_check_constraint(
        op.f("conversations_ck_conversation_room_project_scope_check"),
        "conversations",
        "room_visibility IS NULL OR project_id IS NULL",
    )
    op.create_table(
        "room_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("auto_reply", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id", name="uq_room_participant_org_id"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_participant_conversation",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_members.organization_id", "organization_members.user_id"],
            ondelete="CASCADE",
            name="fk_room_participant_member",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            ondelete="CASCADE",
            name="fk_room_participant_agent",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL) <> (agent_id IS NOT NULL)",
            name=op.f("room_participants_ck_room_participant_one_principal_check"),
        ),
        sa.CheckConstraint(
            "agent_id IS NOT NULL OR auto_reply IS FALSE",
            name=op.f("room_participants_ck_room_participant_auto_reply_agent_check"),
        ),
    )
    op.create_index(
        "ix_room_participants_conversation",
        "room_participants",
        ["organization_id", "conversation_id"],
    )
    op.create_index(
        "ix_room_participants_user",
        "room_participants",
        ["organization_id", "user_id", "conversation_id"],
        unique=False,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_room_participant_user",
        "room_participants",
        ["organization_id", "conversation_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_room_participant_agent",
        "room_participants",
        ["organization_id", "conversation_id", "agent_id"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE room_participants, conversations IN ACCESS EXCLUSIVE MODE")
    bind = op.get_bind()
    has_roster = bool(bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM room_participants)")))
    has_visibility = bool(
        bind.scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM conversations WHERE room_visibility IS NOT NULL)")
        )
    )
    if has_roster or has_visibility:
        raise RuntimeError(
            "room participant evidence exists; export or remove room roster and visibility data before downgrade"
        )
    op.drop_table("room_participants")
    op.drop_constraint(
        op.f("conversations_ck_conversation_room_project_scope_check"),
        "conversations",
        type_="check",
    )
    op.drop_constraint(
        op.f("conversations_ck_conversation_room_visibility_check"),
        "conversations",
        type_="check",
    )
    op.drop_column("conversations", "room_visibility")
