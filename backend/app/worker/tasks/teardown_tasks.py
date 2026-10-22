"""Durable teardown of external state a committed delete left behind.

Two callers hand work here, and for the same reason. `OrganizationService.purge`
commits an organization's relational teardown - its rows, its knowledge bases, its
document records - and the RAG delete paths (`KnowledgeBaseService.delete`,
`RAGDocumentService.delete_by_collection` / `_retire_superseded`) commit the removal
of a collection's or a base's document rows. Both then have external side effects
left over: the stored uploads to unlink and the physical `rag_<collection>` vector
tables to drop.

Running those in the request process is what #1293 and #1347 did with
`spawn_after_commit` - which fixed the *ordering* (a rollback no longer strands a
restored row on a gone file or table) but not the *durability*: the in-process task
was lost the moment the process that queued it died (#1349). A Prefect run made it
survive the process, but was submitted after the commit, so a crash between the two
still lost it. Now the cleanup is a job written in the delete's own transaction
(#2219): it exists exactly when the delete does, and a worker retries it.
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.services.background_jobs import enqueue
from app.worker.jobs import CLEANUP_EXTERNAL_STATE, CleanupExternalState, Restamp

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.rag.vectorstore import PgVectorStore

logger = logging.getLogger(__name__)

# One job carries at most this many storage paths, and at most this many re-stamp
# entries. A large organization - or a large collection - can leave tens of
# thousands of files behind; chunked, each job's row stays small, and a retry
# re-attempts one chunk rather than the whole purge.
_MAX_PATHS_PER_JOB = 500
_MAX_RESTAMPS_PER_JOB = 500

# A reservation older than this is treated as stuck. The normal cleanup releases a
# name within seconds of the commit, and even a job exhausting its three attempts
# clears in minutes; an hour is well past both, so a reservation that outlives it
# lost its cleanup to a drop that fails for good - and its name is blocked with
# nothing left to reattempt it (#1364).
_RESERVATION_MAX_AGE = timedelta(hours=1)


async def queue_external_state_cleanup(
    db: AsyncSession,
    storage_paths: list[str],
    collections: list[str],
    restamps: list[Restamp] | None = None,
    *,
    prefixes: list[str] | None = None,
    required_paths: list[str] | None = None,
    organization_id: UUID | None = None,
) -> None:
    """Queue a delete's external-state cleanup, in the delete's own transaction.

    The paths, the required paths and the re-stamps are each chunked across
    jobs, independently, and zipped onto as many jobs as the longest needs;
    collections and prefixes ride the first job only - `delete_collection` and
    `delete_prefix` are idempotent, but one pass over them is enough.
    `required_paths` are unlinked like `storage_paths`, but one the store
    refuses fails the job so it is retried. `organization_id` is for the panel
    only: the organization may be the thing being deleted.
    """
    restamps = restamps or []
    prefixes = prefixes or []
    required_paths = required_paths or []
    path_chunks = [
        storage_paths[i : i + _MAX_PATHS_PER_JOB]
        for i in range(0, len(storage_paths), _MAX_PATHS_PER_JOB)
    ]
    required_chunks = [
        required_paths[i : i + _MAX_PATHS_PER_JOB]
        for i in range(0, len(required_paths), _MAX_PATHS_PER_JOB)
    ]
    restamp_chunks = [
        restamps[i : i + _MAX_RESTAMPS_PER_JOB]
        for i in range(0, len(restamps), _MAX_RESTAMPS_PER_JOB)
    ]
    for index in range(max(len(path_chunks), len(required_chunks), len(restamp_chunks), 1)):
        await enqueue(
            db,
            CLEANUP_EXTERNAL_STATE,
            CleanupExternalState(
                storage_paths=path_chunks[index] if index < len(path_chunks) else [],
                collections=collections if index == 0 else [],
                restamps=restamp_chunks[index] if index < len(restamp_chunks) else [],
                prefixes=prefixes if index == 0 else [],
                required_paths=required_chunks[index] if index < len(required_chunks) else [],
            ),
            organization_id=organization_id,
        )


@asynccontextmanager
async def _vector_store() -> AsyncGenerator[PgVectorStore]:
    """A `PgVectorStore` on an engine built for one job and disposed after it.

    Per job, so its pool is bounded by the job that opened it and closed on every
    way out - the reason `rag_tasks._ingestion_service` does the same (#948).
    """
    from app.services.embedding_resolution import embeddings_for_collection
    from app.services.rag.embeddings import EmbeddingService
    from app.services.rag.vectorstore import PgVectorStore

    rag_settings = settings.rag
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        yield PgVectorStore(
            settings=rag_settings,
            embedding_service=EmbeddingService(settings=rag_settings),
            resolver=embeddings_for_collection,
            engine=engine,
        )
    finally:
        await engine.dispose()


async def _drop_then_release(store: PgVectorStore, db: AsyncSession, collection: str) -> bool:
    """Drop a reserved collection's vector table, then free its reservation.

    Dropped first and released only then, so a claim never sees the name free while
    its populated table still exists; a drop that fails leaves the reservation in
    place for a retry rather than freeing a name whose table may still hold data
    (#1362). `delete_collection` issues `DROP TABLE IF EXISTS`, so a retry that drops
    a table already gone is a no-op. The caller holds the teardown lock across this,
    serialising it against a claim's reservation check (#1355).
    """
    from app.repositories import collection_teardown_repo

    try:
        await store.delete_collection(collection)
    except SQLAlchemyError as exc:
        logger.warning("Failed to drop collection %s: %s", collection, exc)
        return False
    await collection_teardown_repo.release(db, collection)
    return True


async def cleanup_external_state(
    storage_paths: list[str],
    collections: list[str],
    restamps: list[Restamp] | None = None,
    prefixes: list[str] | None = None,
    required_paths: list[str] | None = None,
) -> dict[str, int]:
    """Unlink a committed delete's stored uploads and drop its unreferenced vector tables.

    Runs after the rows that named this state are committed-gone, so the paths and
    collection names it is handed are all that is left of them.

    Idempotent, because the job's retries must be safe: unlinking a file already gone
    is a no-op, and the drop issues `DROP TABLE IF EXISTS`. The delete path decided
    each name should be dropped and reserved it against reuse (`collection_teardowns`,
    #1362), so a reserved name is dropped whatever now claims it - the reservation
    blocked any legitimate claim. A name with no reservation falls back to the
    reference check, so it does not drop a name reclaimed since. The drop, the
    ordered release and the lock live in :func:`_drop_then_release`.

    `restamps` are the personal bases an organization purge orphaned: each
    untags that org's rows for that base's own
    surviving documents on a table the base still keeps alive, so its new
    `vector_tenant=None` reaches them again rather than leaving them stranded behind
    the `IS NULL` read scope (#1684). The base's surviving `parent_doc_id`s are
    resolved inside the store's one update statement, from `rag_documents` - so a
    document deleted before or concurrently with this run is no longer among them
    and its rows are left stamped (untagging them would un-delete it) rather than
    resurrected, with no window between a separate read and the update for the id set
    to go stale. Re-stamping is idempotent - a table already dropped is a no-op and
    an absent tag strips to nothing - so it is safe under the job's retries; a
    re-stamp that fails is raised below so those retries actually re-run it, because
    a base left stamped with the deleted org is unreadable and undeletable and has no
    other safety net (#1684).

    `prefixes` are removed whole - an organization's generated media, whose rows
    went with it (#2310). A prefix the store would not remove is raised below,
    like a re-stamp, so the retries re-run it: those bytes have no row left to
    find them by. `required_paths` are single files in the same position - a
    deleted conversation's or account's generated media - and a refused one is
    raised the same way.
    """
    from app.core.exceptions import DatabaseError, ExternalServiceError
    from app.db.locks import LockScope, hold_name
    from app.db.session import get_worker_db_context
    from app.repositories import collection_teardown_repo, knowledge_base_repo
    from app.services.file_storage import get_file_storage

    restamps = restamps or []
    prefixes = prefixes or []
    required_paths = required_paths or []
    storage = get_file_storage()
    for storage_path in storage_paths:
        # Best-effort but not silent: the row that named this file is committed-gone,
        # so a swallowed failure leaves an orphan nothing else can find - the warning
        # is its only remaining trace of which path it was (#1293).
        try:
            await storage.delete(storage_path)
        except Exception as exc:
            logger.warning("Failed to unlink stored file %s: %s", storage_path, exc)

    required_failures: list[str] = []
    for storage_path in required_paths:
        try:
            await storage.delete(storage_path)
        except Exception as exc:
            logger.warning("Failed to unlink stored file %s: %s", storage_path, exc)
            required_failures.append(storage_path)

    prefix_failures: list[str] = []
    for prefix in prefixes:
        try:
            await storage.delete_prefix(prefix)
        except Exception as exc:
            logger.warning("Failed to remove stored prefix %s: %s", prefix, exc)
            prefix_failures.append(prefix)

    dropped = 0
    restamped = 0
    restamp_failures: list[str] = []
    if collections or restamps:
        async with _vector_store() as store, get_worker_db_context() as db:
            for collection in collections:
                await hold_name(db, LockScope.COLLECTION_TEARDOWN, collection)
                # A reserved name drops unconditionally; one with no reservation
                # falls back to the reference check and does not drop a name that
                # was reclaimed since it was queued (#1362 review, #913).
                reserved = await collection_teardown_repo.is_reserved(db, collection)
                if not reserved and await knowledge_base_repo.list_by_collection_name(
                    db, collection
                ):
                    continue
                if await _drop_then_release(store, db, collection):
                    dropped += 1
            for restamp in restamps:
                collection = restamp.collection
                # Isolated per entry so one bad re-stamp does not abort the rest, but
                # collected rather than swallowed: the org row that named this state
                # is committed-gone and the personal base survives, so a re-stamp
                # left undone strands the base behind the IS NULL scope with no sweep
                # to reattempt it. The store resolves the base's surviving documents
                # inside its update, so a document deleted since (or concurrently) is
                # absent and stays stamped rather than un-deleted (#1684).
                try:
                    await store.restamp_documents_to_untagged(
                        collection, restamp.organization_id, restamp.knowledge_base_id
                    )
                except SQLAlchemyError as exc:
                    logger.warning("Failed to re-stamp collection %s: %s", collection, exc)
                    restamp_failures.append(collection)
                else:
                    restamped += 1

    logger.info(
        "external_state_cleanup",
        extra={
            "unlinked": len(storage_paths) + len(required_paths),
            "dropped": dropped,
            "restamped": restamped,
        },
    )
    # Raised after the loop, not inside it, so every entry is attempted and the drops
    # and unlinks still complete; the job then fails and its retries re-run the whole
    # idempotent cleanup, re-attempting the re-stamps that could not commit (#1684).
    if restamp_failures:
        raise DatabaseError(
            message="Failed to re-stamp orphaned personal knowledge bases on organization purge",
            details={"collections": restamp_failures},
        )
    if prefix_failures or required_failures:
        raise ExternalServiceError(
            message="Failed to remove stored files on delete",
            details={"prefixes": prefix_failures, "storage_paths": required_failures},
        )
    return {
        "unlinked": len(storage_paths) + len(required_paths),
        "dropped": dropped,
        "restamped": restamped,
    }


async def sweep_teardown_reservations() -> dict[str, int]:
    """Reattempt the drop for reservations whose durable cleanup never finished.

    A reservation is committed with its delete and released the instant the drop runs,
    so one older than `_RESERVATION_MAX_AGE` lost its cleanup to a drop that fails
    for good, or predates the queued cleanup - and blocks its name with
    nothing left to reattempt it (#1364). This is that reattempt: for each stale
    reservation it takes the teardown lock, re-checks the name is still reserved (a
    normal cleanup, or an earlier sweep, may have finished it since the scan), and
    drops the table and releases the name. A name reclaimed since it was reserved
    cannot reach here - `claim` refuses a reserved name and uploads to one are refused
    (#1362, #1364) - so a lingering table under a reserved name is always that
    teardown's, safe to drop.
    """
    from app.db.locks import LockScope, hold_name
    from app.db.session import get_worker_db_context
    from app.repositories import collection_teardown_repo

    cutoff = datetime.now(UTC) - _RESERVATION_MAX_AGE
    dropped = 0
    async with get_worker_db_context() as db:
        stale = await collection_teardown_repo.list_stale(db, older_than=cutoff)
        if not stale:
            return {"swept": 0, "dropped": 0}
        async with _vector_store() as store:
            for row in stale:
                collection = row.collection_name
                try:
                    await hold_name(db, LockScope.COLLECTION_TEARDOWN, collection)
                    if not await collection_teardown_repo.is_reserved(db, collection):
                        continue
                    if await _drop_then_release(store, db, collection):
                        dropped += 1
                except Exception:
                    # One bad tombstone must not disable the sweep. A legacy name
                    # current validation rejects raises from `_table` (a
                    # `BadRequestError`, not the `SQLAlchemyError` `_drop_then_release`
                    # catches), so isolate every reservation and carry on - the row
                    # stays reserved, blocking a name that is already unusable (#1364).
                    logger.exception("teardown_reservation_sweep skipped %s", collection)
    if dropped:
        logger.warning("teardown_reservation_sweep dropped %d stuck reservation(s)", dropped)
    return {"swept": len(stale), "dropped": dropped}


async def run_external_state_cleanup(job: CleanupExternalState) -> dict[str, int]:
    """The job `queue_external_state_cleanup` queues."""
    return await cleanup_external_state(
        job.storage_paths, job.collections, job.restamps, job.prefixes, job.required_paths
    )
