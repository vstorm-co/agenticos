"""Knowledge gaps: the searches agents made, and the misses grouped into topics.

`knowledge_searches` keeps one row per knowledge search an agent made during a
run, with the best cosine similarity it returned, so the searches that found
nothing relevant can be told apart afterwards. Rows cascade with their run and
their conversation, so retention and deletion reach them with no code of their
own. `knowledge_gap_topics` groups the misses of one knowledge base by meaning
and `knowledge_gap_members` says which searches each topic holds; a topic copies
no question, and keeps only the draft a model wrote for it on request.

`agents.kind` gains `drafter`, the kind of the system agent that writes those
drafts. The downgrade makes such an agent an ordinary one, as dropping the
column made a judge one, and clears its `system_key`, so an upgrade again seeds
a fresh drafter rather than finding an agent anybody may chat with under the
drafter's key. It then drops the new tables and loses only what was written
into them.

Revision ID: 0149_knowledge_gaps
Revises: 0148_eval_runs
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0149_knowledge_gaps"
down_revision: str | None = "0148_eval_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", "kind IN ('agent', 'judge', 'drafter')")
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
    op.create_table(
        "knowledge_gap_topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("knowledge_base_id", sa.UUID(), nullable=False),
        sa.Column("centroid", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("dismissed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_title", sa.Text(), nullable=True),
        sa.Column("draft_content", sa.Text(), nullable=True),
        sa.Column(
            "draft_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("draft_unverified", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draft_run_id", sa.UUID(), nullable=True),
        sa.Column("drafted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'dismissed')",
            name=op.f("knowledge_gap_topics_ck_knowledge_gap_topic_status_check"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("knowledge_gap_topics_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name=op.f("knowledge_gap_topics_knowledge_base_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["draft_run_id"],
            ["agent_runs.id"],
            name=op.f("knowledge_gap_topics_draft_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["drafted_by_user_id"],
            ["users.id"],
            name=op.f("knowledge_gap_topics_drafted_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dismissed_by_user_id"],
            ["users.id"],
            name=op.f("knowledge_gap_topics_dismissed_by_user_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("knowledge_gap_topics_pkey")),
    )
    op.create_index(
        op.f("knowledge_gap_topics_organization_id_idx"),
        "knowledge_gap_topics",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("knowledge_gap_topics_knowledge_base_id_idx"),
        "knowledge_gap_topics",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_table(
        "knowledge_gap_members",
        sa.Column("topic_id", sa.UUID(), nullable=False),
        sa.Column("search_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_gap_topics.id"],
            name=op.f("knowledge_gap_members_topic_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_id"],
            ["knowledge_searches.id"],
            name=op.f("knowledge_gap_members_search_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("topic_id", "search_id", name=op.f("knowledge_gap_members_pkey")),
    )
    op.create_index(
        op.f("knowledge_gap_members_search_id_idx"),
        "knowledge_gap_members",
        ["search_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute("UPDATE agents SET kind = 'agent', system_key = NULL WHERE kind = 'drafter'")
    op.drop_constraint("ck_agent_kind", "agents", type_="check")
    op.create_check_constraint("ck_agent_kind", "agents", "kind IN ('agent', 'judge')")
    op.drop_index(op.f("knowledge_gap_members_search_id_idx"), table_name="knowledge_gap_members")
    op.drop_table("knowledge_gap_members")
    op.drop_index(
        op.f("knowledge_gap_topics_knowledge_base_id_idx"), table_name="knowledge_gap_topics"
    )
    op.drop_index(
        op.f("knowledge_gap_topics_organization_id_idx"), table_name="knowledge_gap_topics"
    )
    op.drop_table("knowledge_gap_topics")
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
