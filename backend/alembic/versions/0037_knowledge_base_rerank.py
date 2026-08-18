"""Which reranker - and whose key - a collection reranks search results with.

Retrieval fetches candidates by vector similarity and returns the top ones. A
reranker is a second pass: a model scores each candidate against the query
directly and reorders them, which is more accurate than the distance the vector
index sorts by. It is optional and off by default.

Two nullable columns, mirroring the embedding pair. `rerank_model` is the
reranker's name; `rerank_secret_id` is the organization vault key that pays for
it. Reranking runs only when *both* are set - either NULL leaves retrieval
exactly as it was, so existing rows and unconfigured deployments are unchanged
by this migration. SET NULL on delete for the same reason the embedding key is:
losing the key drops reranking, it does not take document search down. Unlike
the embedding key there is no deployment fallback - a reranker with no key is
simply off.

Revision ID: 0037_knowledge_base_rerank
Revises: 0036_conversation_reminder_state
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037_knowledge_base_rerank"
down_revision: str | None = "0036_conversation_reminder_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("rerank_model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("rerank_secret_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        op.f("knowledge_bases_rerank_secret_id_fkey"),
        "knowledge_bases",
        "organization_secrets",
        ["rerank_secret_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("knowledge_bases_rerank_secret_id_fkey"),
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_column("knowledge_bases", "rerank_secret_id")
    op.drop_column("knowledge_bases", "rerank_model")
