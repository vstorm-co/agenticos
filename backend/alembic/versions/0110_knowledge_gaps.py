"""Knowledge gaps: the searches agents made, and the misses grouped into topics.

`knowledge_searches` keeps one row per knowledge search an agent made during a
run, with the best cosine similarity it returned, so the searches that found
nothing relevant can be told apart afterwards. Rows cascade with their run and
their conversation, so retention and deletion reach them with no code of their
own. Nothing existing is touched, so the downgrade drops the new tables and
loses only what was written into them.

Revision ID: 0110_knowledge_gaps
Revises: 0106_datasets
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0110_knowledge_gaps"
down_revision: str | None = "0106_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_searches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("knowledge_base_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("top_similarity", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("knowledge_searches_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("knowledge_searches_run_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("knowledge_searches_agent_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("knowledge_searches_conversation_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("knowledge_searches_pkey")),
    )
    op.create_index(
        op.f("knowledge_searches_organization_id_idx"),
        "knowledge_searches",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("knowledge_searches_run_id_idx"), "knowledge_searches", ["run_id"], unique=False
    )
    op.create_index(
        op.f("knowledge_searches_agent_id_idx"), "knowledge_searches", ["agent_id"], unique=False
    )
    op.create_index(
        op.f("knowledge_searches_conversation_id_idx"),
        "knowledge_searches",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_searches_knowledge_base_ids",
        "knowledge_searches",
        ["knowledge_base_ids"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_searches_knowledge_base_ids",
        table_name="knowledge_searches",
        postgresql_using="gin",
    )
    op.drop_index(op.f("knowledge_searches_conversation_id_idx"), table_name="knowledge_searches")
    op.drop_index(op.f("knowledge_searches_agent_id_idx"), table_name="knowledge_searches")
    op.drop_index(op.f("knowledge_searches_run_id_idx"), table_name="knowledge_searches")
    op.drop_index(op.f("knowledge_searches_organization_id_idx"), table_name="knowledge_searches")
    op.drop_table("knowledge_searches")
