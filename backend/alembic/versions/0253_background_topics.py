"""Keep delegated topics and their completion separate from a live chat turn.

A task records its source, fresh topic, fixed agent versions and exact local
device. A short-lived admission row prevents its return from racing foreground
turns without holding a database connection across model calls. Neither table
introduces watches, memory, or an automatic replay of external side effects.

Revision ID: 0253_background_topics
Revises: 0252_index_rag_parent_doc_id
Create Date: 2026-11-03 22:56:25.721369

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0253_background_topics"
down_revision: str | None = "0252_index_rag_parent_doc_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source_conversation_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=False),
        sa.Column("source_agent_id", sa.UUID(), nullable=False),
        sa.Column("source_version_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("source_model_profile_id", sa.UUID(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("local_target", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("delivery", sa.String(length=16), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("return_run_id", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "delivery IN ('pending', 'running', 'delivered', 'interrupted', 'withdrawn')",
            name=op.f("conversation_tasks_delivery_check"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'awaiting_answer', 'completed', 'failed', 'cancelled', 'interrupted')",
            name=op.f("conversation_tasks_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("conversation_tasks_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_conversation_task_topic",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "source_conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_conversation_task_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("conversation_tasks_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["return_run_id"],
            ["agent_runs.id"],
            name=op.f("conversation_tasks_return_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("conversation_tasks_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id"],
            ["agents.id"],
            name=op.f("conversation_tasks_source_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["agent_runs.id"],
            name=op.f("conversation_tasks_source_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["agent_versions.id"],
            name=op.f("conversation_tasks_source_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("conversation_tasks_user_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["agent_versions.id"],
            name=op.f("conversation_tasks_version_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("conversation_tasks_pkey")),
        sa.UniqueConstraint("return_run_id", name=op.f("conversation_tasks_return_run_id_key")),
        sa.UniqueConstraint("run_id", name=op.f("conversation_tasks_run_id_key")),
        sa.UniqueConstraint("source_run_id", "tool_call_id", name="uq_conversation_task_call"),
    )
    op.create_index(
        "conversation_tasks_person_idx",
        "conversation_tasks",
        ["organization_id", "user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "conversation_tasks_source_idx",
        "conversation_tasks",
        ["organization_id", "source_conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "conversation_tasks_pending_return_idx",
        "conversation_tasks",
        ["created_at"],
        postgresql_where=sa.text(
            "delivery = 'pending' AND status IN ('completed', 'failed', 'cancelled', 'interrupted')"
        ),
    )
    op.create_index(
        "conversation_tasks_unsettled_idx",
        "conversation_tasks",
        ["run_id"],
        postgresql_where=sa.text("status IN ('running', 'awaiting_approval', 'awaiting_answer')"),
    )
    op.create_table(
        "conversation_turn_claims",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("background", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("conversation_turn_claims_conversation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("conversation_turn_claims_pkey")),
    )
    op.create_index(
        "conversation_turn_claims_topic_idx",
        "conversation_turn_claims",
        ["conversation_id", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("conversation_turn_claims_topic_idx", table_name="conversation_turn_claims")
    op.drop_table("conversation_turn_claims")
    op.drop_index("conversation_tasks_unsettled_idx", table_name="conversation_tasks")
    op.drop_index("conversation_tasks_pending_return_idx", table_name="conversation_tasks")
    op.drop_index("conversation_tasks_source_idx", table_name="conversation_tasks")
    op.drop_index("conversation_tasks_person_idx", table_name="conversation_tasks")
    op.drop_table("conversation_tasks")
