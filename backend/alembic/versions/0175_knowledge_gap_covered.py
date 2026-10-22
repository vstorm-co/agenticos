"""Knowledge gaps closed from their tab: covered topics, refusals, cited context files.

`knowledge_gap_topics` gains the `covered` status and who covered it with which
document, so a person who adds a topic's content to its knowledge base sees the
topic say so; a document deleted later leaves the topic open again. It also
gains `draft_already_covered`, set when the drafter found the questions already
answered by a context file or a document, and `draft_by_model`, whether a model
or a person wrote the draft's text - every draft before it was the drafter's. `rag_documents` gains the topic a
document was added from.

`knowledge_gap_classifications` accepts `refused`: the agent rightly refused a
request outside its rules, so the answer's misses are no gap.

The downgrade reopens covered topics and forgets refusals - those answers are
read again by the next check - and drops what this revision added.

Revision ID: 0175_knowledge_gap_covered
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0175_knowledge_gap_covered"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS = "knowledge_gap_topics_ck_knowledge_gap_topic_status_check"
_SIGNAL = "knowledge_gap_classifications_ck_classification_signal_check"


def _check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, condition)


def upgrade() -> None:
    _check(_STATUS, "knowledge_gap_topics", "status IN ('open', 'dismissed', 'covered')")
    _check(
        _SIGNAL,
        "knowledge_gap_classifications",
        "signal IN ('answer', 'rating', 'none', 'refused')",
    )
    op.add_column(
        "knowledge_gap_topics", sa.Column("covered_by_document_id", sa.UUID(), nullable=True)
    )
    op.add_column("knowledge_gap_topics", sa.Column("covered_by_user_id", sa.UUID(), nullable=True))
    op.add_column(
        "knowledge_gap_topics",
        sa.Column("covered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_gap_topics",
        sa.Column("draft_already_covered", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "knowledge_gap_topics",
        sa.Column("draft_by_model", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Every draft so far was the drafter's: nothing else could write one.
    op.execute(
        "UPDATE knowledge_gap_topics SET draft_by_model = true WHERE draft_content IS NOT NULL"
    )
    op.create_foreign_key(
        op.f("knowledge_gap_topics_covered_by_document_id_fkey"),
        "knowledge_gap_topics",
        "rag_documents",
        ["covered_by_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("knowledge_gap_topics_covered_by_user_id_fkey"),
        "knowledge_gap_topics",
        "users",
        ["covered_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("knowledge_gap_topics_covered_by_document_id_idx"),
        "knowledge_gap_topics",
        ["covered_by_document_id"],
        unique=False,
    )
    op.add_column("rag_documents", sa.Column("knowledge_gap_topic_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("rag_documents_knowledge_gap_topic_id_fkey"),
        "rag_documents",
        "knowledge_gap_topics",
        ["knowledge_gap_topic_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("rag_documents_knowledge_gap_topic_id_idx"),
        "rag_documents",
        ["knowledge_gap_topic_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("rag_documents_knowledge_gap_topic_id_idx"), table_name="rag_documents")
    op.drop_constraint(
        op.f("rag_documents_knowledge_gap_topic_id_fkey"), "rag_documents", type_="foreignkey"
    )
    op.drop_column("rag_documents", "knowledge_gap_topic_id")
    op.drop_index(
        op.f("knowledge_gap_topics_covered_by_document_id_idx"), table_name="knowledge_gap_topics"
    )
    op.drop_constraint(
        op.f("knowledge_gap_topics_covered_by_user_id_fkey"),
        "knowledge_gap_topics",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("knowledge_gap_topics_covered_by_document_id_fkey"),
        "knowledge_gap_topics",
        type_="foreignkey",
    )
    op.drop_column("knowledge_gap_topics", "draft_by_model")
    op.drop_column("knowledge_gap_topics", "draft_already_covered")
    op.drop_column("knowledge_gap_topics", "covered_at")
    op.drop_column("knowledge_gap_topics", "covered_by_user_id")
    op.drop_column("knowledge_gap_topics", "covered_by_document_id")
    op.execute("UPDATE knowledge_gap_topics SET status = 'open' WHERE status = 'covered'")
    op.execute("DELETE FROM knowledge_gap_classifications WHERE signal = 'refused'")
    _check(_SIGNAL, "knowledge_gap_classifications", "signal IN ('answer', 'rating', 'none')")
    _check(_STATUS, "knowledge_gap_topics", "status IN ('open', 'dismissed')")
