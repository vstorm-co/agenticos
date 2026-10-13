"""A sync source's claim on a document it lists."""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RAGDocumentClaim(Base):
    """A row per (document, sync source): this source lists the document's address.

    A document had one owner, `rag_documents.sync_source_id`, and it was whichever
    source ingested it last. Two sources feeding one collection can both list an
    address - two sites whose roots overlap, a copied Drive source - and when the
    owner stopped listing it the sync removed it, although the other still did
    (#1879). With a claim per source, a sync that stops listing a document drops
    its own claim, and removes the document only when no other source feeding the
    collection still claims it.

    Both foreign keys cascade. A removed document has nothing left to claim, and
    a deleted source no longer lists anything: the document outlives it, and is
    removed by the last source still claiming it, or kept for good if none does.
    The pair is the primary key, so claiming twice is a conflict rather than a
    second row. The index is for the other direction, "this source's documents",
    which every sync reads.
    """

    __tablename__ = "rag_document_claims"

    rag_document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rag_documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sync_source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sync_sources.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<RAGDocumentClaim(rag_document_id={self.rag_document_id}, "
            f"sync_source_id={self.sync_source_id})>"
        )
