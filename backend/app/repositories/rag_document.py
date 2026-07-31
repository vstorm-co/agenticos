"""RAG document repository (PostgreSQL async).

Contains database operations for RAGDocument entities.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rag_document import RAGDocument


@dataclass(frozen=True)
class CollectionCounts:
    """What one collection holds, as the listing reports it.

    `documents` counts every tracked row; `indexed` counts only those that
    finished. They differ while something is parsing and stay different when
    something failed, which is exactly the state a listing should be able to
    show - "12 documents" on a collection where four died reads as working.
    """

    documents: int
    chunks: int
    indexed: int


async def get_by_id(db: AsyncSession, doc_id: UUID) -> RAGDocument | None:
    """Get a RAG document by ID."""
    return await db.get(RAGDocument, doc_id)


async def get_all(
    db: AsyncSession,
    *,
    collections: list[str],
) -> list[RAGDocument]:
    """Documents tracked in the named collections, newest first.

    Filtering on `organization_id` would be the obvious alternative and is not
    equivalent: the column is nullable and a document ingested by a sync task
    has no organization stamped on it, so an org filter silently hides those
    while a collection filter does not. The collection is what the
    `knowledge_bases` row authorized, so the collection is what this asks for.
    """
    if not collections:
        return []
    query = (
        select(RAGDocument)
        .where(RAGDocument.collection_name.in_(collections))
        .order_by(RAGDocument.created_at.desc())
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_for_kb(
    db: AsyncSession,
    kb_id: UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[RAGDocument], int]:
    """Page through documents linked to a Knowledge Base. Returns (rows, total)."""
    base = select(RAGDocument).where(RAGDocument.knowledge_base_id == kb_id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (await db.execute(base.order_by(RAGDocument.created_at.desc()).offset(skip).limit(limit)))
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def create(
    db: AsyncSession,
    *,
    collection_name: str,
    filename: str,
    filesize: int,
    filetype: str,
    storage_path: str,
    status: str = "processing",
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    ingestion_config: dict[str, object] | None = None,
    ingestion_override: dict[str, object] | None = None,
    image_description_model: str | None = None,
    embedding_model: str | None = None,
) -> RAGDocument:
    """Create a new RAG document record."""
    doc = RAGDocument(
        collection_name=collection_name,
        filename=filename,
        filesize=filesize,
        filetype=filetype,
        storage_path=storage_path,
        status=status,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        ingestion_config=ingestion_config or {},
        ingestion_override=ingestion_override,
        image_description_model=image_description_model,
        embedding_model=embedding_model,
    )
    db.add(doc)
    await db.flush()
    return doc


async def update_status(
    db: AsyncSession,
    doc_id: UUID,
    *,
    status: str,
    error_message: str | None = None,
    vector_document_id: str | None = None,
    chunk_count: int | None = None,
    completed_at: Any = None,
) -> RAGDocument | None:
    """Update the processing status of a RAG document."""
    doc = await db.get(RAGDocument, doc_id)
    if not doc:
        return None
    doc.status = status
    if error_message is not None:
        doc.error_message = error_message
    if vector_document_id is not None:
        doc.vector_document_id = vector_document_id
    if chunk_count is not None:
        doc.chunk_count = chunk_count
    if completed_at is not None:
        doc.completed_at = completed_at
    await db.flush()
    return doc


async def delete(db: AsyncSession, doc_id: UUID) -> bool:
    """Delete a RAG document by ID."""
    doc = await db.get(RAGDocument, doc_id)
    if not doc:
        return False
    await db.delete(doc)
    await db.flush()
    return True


async def sum_filesize_for_org(db: AsyncSession, org_id: UUID) -> int:
    """Return total bytes of RAG documents stored for an organization."""
    result = await db.execute(
        select(func.coalesce(func.sum(RAGDocument.filesize), 0)).where(
            RAGDocument.organization_id == org_id
        )
    )
    return int(result.scalar_one())


async def counts_by_collection(
    db: AsyncSession, *, collections: list[str]
) -> dict[str, CollectionCounts]:
    """How much each named collection actually holds, in one query.

    One `GROUP BY` rather than a call per collection: this feeds a listing, and
    the per-collection alternative (`GET /rag/collections/{name}/info`) asks the
    vector store once per row - twenty collections, twenty round trips, to
    render one page.

    Counted from `rag_documents` rather than from the vectors, and the
    difference is the point. This table is what the upload wrote, so a document
    still parsing and a document that failed both appear here and neither has a
    vector yet. A count taken from the vector store would show a collection
    someone just uploaded to as empty, which is the one moment they are looking.

    Collections with no rows are absent from the result rather than present as
    zero, so callers read it with a default - a name that was never written to
    has no row to group.
    """
    if not collections:
        return {}
    result = await db.execute(
        select(
            RAGDocument.collection_name,
            func.count(),
            func.coalesce(func.sum(RAGDocument.chunk_count), 0),
            func.count().filter(RAGDocument.status == "completed"),
        )
        .where(RAGDocument.collection_name.in_(collections))
        .group_by(RAGDocument.collection_name)
    )
    return {
        name: CollectionCounts(documents=int(documents), chunks=int(chunks), indexed=int(indexed))
        for name, documents, chunks, indexed in result.all()
    }


async def delete_by_collection(db: AsyncSession, collection_name: str) -> int:
    """Delete all RAG document records for a collection. Returns affected row count."""
    result = await db.execute(
        sql_delete(RAGDocument).where(RAGDocument.collection_name == collection_name)
    )
    await db.flush()
    return result.rowcount  # ty: ignore[unresolved-attribute]
