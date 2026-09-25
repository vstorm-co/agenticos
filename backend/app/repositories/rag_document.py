"""RAG document repository (PostgreSQL async).

Contains database operations for RAGDocument entities.
"""

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import exists, func, literal, select, tuple_
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.db.models.rag_document_claim import RAGDocumentClaim
from app.db.models.sync_source import SyncSource


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
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[RAGDocument], int]:
    """A page of documents tracked in the named collections, newest first.

    Returns `(rows, total)`, the same shape as `get_for_kb`: without a bound this
    selected and serialized every row across the caller's collections, which grows
    without limit with tenant data (#27).

    Filtering on `organization_id` would be the obvious alternative and is not
    equivalent: the column is nullable and a document ingested by a sync task
    has no organization stamped on it, so an org filter silently hides those
    while a collection filter does not. The collection is what the
    `knowledge_bases` row authorized, so the collection is what this asks for.
    """
    if not collections:
        return [], 0
    base = select(RAGDocument).where(RAGDocument.collection_name.in_(collections))
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                # `id` breaks ties: a bulk import lands many rows in one
                # microsecond, and without a unique secondary key their
                # `created_at DESC` order is not stable across the pages the
                # caller reads them in (#1103).
                base.order_by(RAGDocument.created_at.desc(), RAGDocument.id.desc())
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


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
        (
            await db.execute(
                # `id` breaks ties so a page boundary through rows sharing a
                # `created_at` neither repeats nor skips one (#1103).
                base.order_by(RAGDocument.created_at.desc(), RAGDocument.id.desc())
                .offset(skip)
                .limit(limit)
            )
        )
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
    source_path: str | None = None,
    sync_source_id: UUID | None = None,
    status: DocumentStatus = DocumentStatus.PROCESSING,
    organization_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    ingestion_config: dict[str, object] | None = None,
    ingestion_override: dict[str, object] | None = None,
    image_description_model: str | None = None,
    embedding_model: str | None = None,
    organizational_unit: str | None = None,
    initiated_by_user_id: UUID | None = None,
) -> RAGDocument:
    """Create a new RAG document record, claimed by `sync_source_id` when a sync opens it."""
    doc = RAGDocument(
        collection_name=collection_name,
        filename=filename,
        filesize=filesize,
        filetype=filetype,
        storage_path=storage_path,
        source_path=source_path,
        status=status,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        ingestion_config=ingestion_config or {},
        ingestion_override=ingestion_override,
        image_description_model=image_description_model,
        embedding_model=embedding_model,
        organizational_unit=organizational_unit,
        initiated_by_user_id=initiated_by_user_id,
    )
    db.add(doc)
    await db.flush()
    if sync_source_id is not None:
        db.add(RAGDocumentClaim(rag_document_id=doc.id, sync_source_id=sync_source_id))
        await db.flush()
    return doc


async def update_status(
    db: AsyncSession,
    doc_id: UUID,
    *,
    status: DocumentStatus,
    error_message: str | None = None,
    vector_document_id: str | None = None,
    chunk_count: int | None = None,
    completed_at: Any = None,
    ingestion_attempt: int | None = None,
    expected_attempt: int | None = None,
) -> RAGDocument | None:
    """Update the processing status of a RAG document.

    `ingestion_attempt` is bumped only by `retry_ingestion` (#1598), at
    dispatch time - the value it writes is what `complete_ingestion`/
    `fail_ingestion` later compare their own passed `attempt` against, to
    reject a settlement that belongs to an attempt a newer retry has already
    superseded.

    `expected_attempt`, given by those two callers, folds that comparison
    into the same statement as the write instead of a separate read
    beforehand: a read-then-write leaves a window for a concurrent retry's
    bump to land in between them, where a stale settlement that read the old
    attempt just before the bump would still win an unconditional write. A
    conditional `UPDATE ... WHERE ingestion_attempt = ...` re-evaluates the
    predicate against whatever is actually committed at write time instead -
    the same "still holds the claim" guarantee `notification_repo
    .settle_delivery` gives the delivery sweep. Returns `None`, the same as
    a document that no longer exists, when the row has already moved past
    `expected_attempt`.
    """
    if expected_attempt is not None:
        values: dict[str, Any] = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        if vector_document_id is not None:
            values["vector_document_id"] = vector_document_id
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if completed_at is not None:
            values["completed_at"] = completed_at
        if ingestion_attempt is not None:
            values["ingestion_attempt"] = ingestion_attempt
        result = await db.execute(
            sql_update(RAGDocument)
            .where(RAGDocument.id == doc_id, RAGDocument.ingestion_attempt == expected_attempt)
            .values(**values)
            .execution_options(synchronize_session="fetch")
        )
        if not result.rowcount:  # ty: ignore[unresolved-attribute]
            return None
        await db.flush()
        return await db.get(RAGDocument, doc_id)

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
    if ingestion_attempt is not None:
        doc.ingestion_attempt = ingestion_attempt
    await db.flush()
    return doc


async def get_superseded(
    db: AsyncSession,
    *,
    collection_name: str,
    vector_document_id: str,
    keep_id: UUID,
) -> list[RAGDocument]:
    """Rows tracking a vector document that a replacement has just deleted.

    Scoped to one collection because that is what the caller was authorized on.
    `keep_id` is the row doing the replacing, excluded so that this can never
    delete the row whose ingest it is completing - which depends on that row
    already carrying its *new* `vector_document_id` by the time this runs.
    """
    result = await db.execute(
        select(RAGDocument).where(
            RAGDocument.collection_name == collection_name,
            RAGDocument.vector_document_id == vector_document_id,
            RAGDocument.id != keep_id,
        )
    )
    return list(result.scalars().all())


async def discard_failed(db: AsyncSession, *, collection_name: str, source_path: str) -> int:
    """Drop this file's *failed* attempts, and count them.

    A failed parse writes no vectors, so the row it leaves has no
    `vector_document_id` - and `complete_ingestion`'s retirement matches on
    exactly that, which is why a file failing one sync and succeeding the next
    used to leave both rows and inflate the collection's count for good (#996).

    **`ERROR`, not "has no vector id".** Those are not the same set, and treating
    them as one is a race: a `PROCESSING` row belongs to an attempt that is still
    running, and two overlapping ingestions of one source - two manual triggers,
    nothing serialising them - would have the second delete the first's live row.
    The first would then finish, replace the vectors, and find no row to complete,
    leaving one row pointing at deleted vectors and the new vectors tracked by
    nothing. A row left `PROCESSING` by a run that died is a different problem
    with a different fix, and it may describe vectors that exist.

    Matched on `source_path` rather than `filename`, which is the whole reason
    the column exists: `a/readme.md` and `b/readme.md` in one bucket share a
    basename, and matching by name would delete the other file's row.
    """
    result = cast(
        CursorResult[Any],
        await db.execute(
            sql_delete(RAGDocument).where(
                RAGDocument.collection_name == collection_name,
                RAGDocument.source_path == source_path,
                RAGDocument.status == DocumentStatus.ERROR,
                RAGDocument.vector_document_id.is_(None),
            )
        ),
    )
    await db.flush()
    return int(result.rowcount or 0)


async def get_settled_for_sync_source(
    db: AsyncSession, *, sync_source_id: UUID, collection_name: str
) -> list[RAGDocument]:
    """The settled rows one sync source claims in one collection.

    `PROCESSING` is left out for the reason `discard_failed` gives: such a row
    belongs to an attempt that may still be running, and removing it would
    strand the vectors that attempt is about to write. One a dead run left
    behind is `get_stale_for_sync_source`'s, and settled before this is asked.

    Scoped to the source's *current* collection: rows it claimed in one it was
    repointed away from are that collection's now, and a sync of the new one has
    no business reaching them.
    """
    result = await db.execute(
        select(RAGDocument)
        .join(RAGDocumentClaim, RAGDocumentClaim.rag_document_id == RAGDocument.id)
        .where(
            RAGDocumentClaim.sync_source_id == sync_source_id,
            RAGDocument.collection_name == collection_name,
            RAGDocument.status != DocumentStatus.PROCESSING,
        )
    )
    return list(result.scalars().all())


async def get_stale_for_sync_source(
    db: AsyncSession, *, sync_source_id: UUID, collection_name: str
) -> list[RAGDocument]:
    """The `PROCESSING` rows one sync source left in one collection.

    Asked by a run holding the source's run lock, so none of these belongs to a
    run still going: each is what a worker that died mid-file left, whose
    vectors may or may not have been written. A row with no `source_path` is not
    one a sync opened - `_open_document_row` always gives it one - and is left
    for whoever did. A `PROCESSING` row has one claim, the source that opened
    it: other sources claim a row only once it settles (`claim_listed`,
    `add_claims`, `transfer_claims`), so this never reaches a row another
    source's run may still be writing.
    """
    result = await db.execute(
        select(RAGDocument)
        .join(RAGDocumentClaim, RAGDocumentClaim.rag_document_id == RAGDocument.id)
        .where(
            RAGDocumentClaim.sync_source_id == sync_source_id,
            RAGDocument.collection_name == collection_name,
            RAGDocument.status == DocumentStatus.PROCESSING,
            RAGDocument.source_path.is_not(None),
        )
    )
    return list(result.scalars().all())


async def lock_for_removal(db: AsyncSession, doc_id: UUID) -> RAGDocument | None:
    """The row, locked until this transaction ends, or `None` when it is already gone.

    What makes "is this source the document's last claimant" a decision that
    still holds when the row is deleted. Two sources dropping one document at
    once each saw the other's claim, each withdrew its own, and left a
    document nobody claims and no sync would ever remove; a source claiming it
    meanwhile lost its claim with the row. Each now waits for the other's
    transaction: a claim, whose foreign key takes a share lock on this row, as
    much as a removal.
    """
    result = await db.execute(
        select(RAGDocument)
        .where(RAGDocument.id == doc_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def is_claimed_by_another_source(
    db: AsyncSession, doc_id: UUID, *, sync_source_id: UUID
) -> bool:
    """Whether a source other than this one still claims the document for its collection.

    Only a source still feeding the document's collection counts: one repointed
    elsewhere no longer lists anything here, and its old claim must not keep a
    document no source will ever remove.
    """
    result = await db.execute(
        select(
            exists().where(
                RAGDocumentClaim.rag_document_id == doc_id,
                RAGDocumentClaim.sync_source_id != sync_source_id,
                SyncSource.id == RAGDocumentClaim.sync_source_id,
                RAGDocument.id == RAGDocumentClaim.rag_document_id,
                SyncSource.collection_name == RAGDocument.collection_name,
            )
        )
    )
    return bool(result.scalar())


async def delete_claim(db: AsyncSession, doc_id: UUID, *, sync_source_id: UUID) -> None:
    """Withdraw one source's claim on a document, leaving the document."""
    await db.execute(
        sql_delete(RAGDocumentClaim).where(
            RAGDocumentClaim.rag_document_id == doc_id,
            RAGDocumentClaim.sync_source_id == sync_source_id,
        )
    )
    await db.flush()


async def add_claims(db: AsyncSession, doc_id: UUID, *, sync_source_ids: set[UUID]) -> None:
    """Claim one document for each of these sources, keeping claims it already has."""
    if not sync_source_ids:
        return
    await db.execute(
        pg_insert(RAGDocumentClaim)
        .values(
            [
                {"rag_document_id": doc_id, "sync_source_id": source}
                for source in sorted(sync_source_ids)
            ]
        )
        .on_conflict_do_nothing()
    )
    await db.flush()


async def get_claimants(db: AsyncSession, doc_ids: list[UUID]) -> set[UUID]:
    """Every source claiming any of these documents."""
    if not doc_ids:
        return set()
    result = await db.execute(
        select(RAGDocumentClaim.sync_source_id)
        .where(RAGDocumentClaim.rag_document_id.in_(doc_ids))
        .distinct()
    )
    return set(result.scalars().all())


# Two bind parameters a pair: well under asyncpg's 32767 whatever a listing holds.
CLAIM_BATCH = 1000


async def claim_listed(
    db: AsyncSession,
    *,
    sync_source_id: UUID,
    collection_name: str,
    documents: set[tuple[str, str]],
) -> None:
    """Claim the settled rows tracking these `(source_path, vector_document_id)` pairs.

    A sync that finds a listed file already stored - ingested by another
    source, or skipped as unchanged - opens no row for it, so it held no claim
    on it, and the other source dropping it removed a document this one still
    lists. The pair, not the address alone: the stored document came from the
    ingester's tenant-scoped lookup, so matching its id keeps this to the
    document the sync actually compared, never another tenant's row under a
    shared collection name.

    `FOR KEY SHARE`, so a row another source holds for removal is waited for
    and then skipped once it is gone, rather than failing the claim's foreign
    key and the whole sync with it (`lock_for_removal`).
    """
    pairs = sorted(documents)
    for start in range(0, len(pairs), CLAIM_BATCH):
        await db.execute(
            pg_insert(RAGDocumentClaim)
            .from_select(
                ["rag_document_id", "sync_source_id"],
                select(RAGDocument.id, literal(sync_source_id, PG_UUID(as_uuid=True)))
                .where(
                    RAGDocument.collection_name == collection_name,
                    RAGDocument.status == DocumentStatus.DONE,
                    tuple_(RAGDocument.source_path, RAGDocument.vector_document_id).in_(
                        pairs[start : start + CLAIM_BATCH]
                    ),
                )
                .with_for_update(key_share=True),
            )
            .on_conflict_do_nothing()
        )
    await db.flush()


async def transfer_claims(db: AsyncSession, *, from_ids: list[UUID], to_id: UUID) -> None:
    """Copy the claims on `from_ids` onto `to_id`, before the rows they were on are deleted."""
    if not from_ids:
        return
    await db.execute(
        pg_insert(RAGDocumentClaim)
        .from_select(
            ["rag_document_id", "sync_source_id"],
            select(literal(to_id, PG_UUID(as_uuid=True)), RAGDocumentClaim.sync_source_id)
            .where(RAGDocumentClaim.rag_document_id.in_(from_ids))
            .distinct(),
        )
        .on_conflict_do_nothing()
    )
    await db.flush()


async def get_tracked_vector_ids(
    db: AsyncSession, *, collection_name: str, vector_document_ids: set[str]
) -> set[str]:
    """Which of these stored documents a row of the collection points at."""
    if not vector_document_ids:
        return set()
    result = await db.execute(
        select(RAGDocument.vector_document_id).where(
            RAGDocument.collection_name == collection_name,
            RAGDocument.vector_document_id.in_(vector_document_ids),
        )
    )
    return {str(value) for value in result.scalars().all() if value}


async def delete(db: AsyncSession, doc_id: UUID) -> bool:
    """Delete a RAG document by ID."""
    doc = await db.get(RAGDocument, doc_id)
    if not doc:
        return False
    await db.delete(doc)
    await db.flush()
    return True


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
            func.count().filter(RAGDocument.status == DocumentStatus.DONE),
        )
        .where(RAGDocument.collection_name.in_(collections))
        .group_by(RAGDocument.collection_name)
    )
    return {
        name: CollectionCounts(documents=int(documents), chunks=int(chunks), indexed=int(indexed))
        for name, documents, chunks, indexed in result.all()
    }


async def delete_by_collection(db: AsyncSession, collection_name: str) -> list[str]:
    """Delete a collection's document rows, returning their stored file paths.

    Keyed on `collection_name`, so it removes every knowledge base's rows for
    that physical collection - which is what the collection-drop route means. The
    returned `storage_path`s are the uploads the caller still has to unlink; a
    `NULL` one (nothing was stored) is dropped. The bulk delete used to return
    only a rowcount, so the files were orphaned on disk (#1265).
    """
    result = await db.execute(
        sql_delete(RAGDocument)
        .where(RAGDocument.collection_name == collection_name)
        .returning(RAGDocument.storage_path)
    )
    await db.flush()
    return [path for path in result.scalars().all() if path]


async def delete_by_knowledge_base(db: AsyncSession, kb_id: UUID) -> list[str]:
    """Delete a knowledge base's document rows, returning the stored file paths.

    Keyed on `knowledge_base_id`, not `collection_name`: when two tenants back
    onto one physical collection (collection_name is not tenant-unique, #913),
    this removes only the rows belonging to the KB being torn down and leaves the
    other tenant's alone. The returned `storage_path`s are the uploads the caller
    still has to delete from storage - a `NULL` one (nothing was stored) is
    dropped from the list (#1116).
    """
    result = await db.execute(
        sql_delete(RAGDocument)
        .where(RAGDocument.knowledge_base_id == kb_id)
        .returning(RAGDocument.storage_path)
    )
    await db.flush()
    return [path for path in result.scalars().all() if path]
