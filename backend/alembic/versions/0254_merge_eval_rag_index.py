"""Join eval helper snapshots and the released RAG document index.

Preserve both histories so an existing installation on either branch applies
its missing revisions before recording one head.

Revision ID: 0254_merge_eval_rag_index
Revises: 0253_helper_snapshots, 0252_index_rag_parent_doc_id
Create Date: 2026-11-03
"""

from collections.abc import Sequence

revision: str = "0254_merge_eval_rag_index"
down_revision: tuple[str, ...] = (
    "0253_helper_snapshots",
    "0252_index_rag_parent_doc_id",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
