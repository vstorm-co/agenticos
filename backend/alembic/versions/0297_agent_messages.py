"""Direct messages between agents: threads, messages, reactions, files, reads.

One thread per unordered pair of agents in an organization - the pair is
stored in canonical order (`agent_a_id < agent_b_id`) so (A, B) and (B, A)
are the same thread - with messages, emoji reactions from an agent or from
the person reading, links to files already uploaded, and one read watermark
per (thread, person).

No backfill: there is no earlier shape of this data to carry over. The
numbering skips 0296, which a parallel branch holds; if it lands first this
revision needs a merge migration, the same way 0292 merged a forked chain.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0297_agent_messages"
down_revision: str = "0295_tool_approval_consent"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "agent_message_threads",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("agent_a_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("agent_b_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_a_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_b_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "organization_id", "agent_a_id", "agent_b_id", name="uq_agent_message_thread_pair"
        ),
        sa.CheckConstraint("agent_a_id < agent_b_id", name="ck_agent_message_thread_order"),
    )
    op.create_index(
        "ix_agent_message_threads_organization_id",
        "agent_message_threads",
        ["organization_id"],
    )
    op.create_index(
        "ix_agent_message_threads_org_recent",
        "agent_message_threads",
        ["organization_id", "last_message_at"],
    )

    op.create_table(
        "agent_messages",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("sender_agent_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("sender_user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("reply_to_message_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_message_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["reply_to_message_id"], ["agent_messages.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_agent_messages_thread_id", "agent_messages", ["thread_id"])
    op.create_index("ix_agent_messages_organization_id", "agent_messages", ["organization_id"])
    op.create_index("ix_agent_messages_sender_agent_id", "agent_messages", ["sender_agent_id"])
    op.create_index(
        "ix_agent_messages_thread_created", "agent_messages", ["thread_id", "created_at"]
    )

    op.create_table(
        "agent_message_reactions",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("reactor_agent_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("reactor_user_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["message_id"], ["agent_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reactor_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reactor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(reactor_agent_id IS NULL) != (reactor_user_id IS NULL)",
            name="ck_agent_message_reaction_reactor",
        ),
    )
    op.create_index(
        "ix_agent_message_reactions_message_id", "agent_message_reactions", ["message_id"]
    )
    op.create_index(
        "ix_agent_message_reactions_organization_id",
        "agent_message_reactions",
        ["organization_id"],
    )
    op.create_index(
        "uq_agent_message_reaction_agent",
        "agent_message_reactions",
        ["message_id", "reactor_agent_id", "emoji"],
        unique=True,
        postgresql_where=sa.text("reactor_agent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_agent_message_reaction_user",
        "agent_message_reactions",
        ["message_id", "reactor_user_id", "emoji"],
        unique=True,
        postgresql_where=sa.text("reactor_user_id IS NOT NULL"),
    )

    op.create_table(
        "agent_message_attachments",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("chat_file_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["message_id"], ["agent_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chat_file_id"], ["chat_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "chat_file_id", name="uq_agent_message_attachment"),
    )
    op.create_index(
        "ix_agent_message_attachments_message_id",
        "agent_message_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_agent_message_attachments_chat_file_id",
        "agent_message_attachments",
        ["chat_file_id"],
    )
    op.create_index(
        "ix_agent_message_attachments_organization_id",
        "agent_message_attachments",
        ["organization_id"],
    )

    op.create_table(
        "agent_message_reads",
        sa.Column("thread_id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["agent_message_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("agent_message_reads")
    op.drop_table("agent_message_attachments")
    op.drop_table("agent_message_reactions")
    op.drop_table("agent_messages")
    op.drop_table("agent_message_threads")
