"""Durable teardown of external state a committed delete left behind.

Two callers hand work here, and for the same reason. `OrganizationService.purge`
commits an organization's relational teardown - its rows, its knowledge bases, its
document records - and the RAG delete paths (`KnowledgeBaseService.delete`,
`RAGDocumentService.delete_by_collection` / `_retire_superseded`) commit the removal
of a collection's or a base's document rows. Both then have external side effects
left over: the stored uploads to unlink and the physical `rag_<collection>` vector
tables to drop.

Running those in the request process is what #1293 and #1347 did with
`spawn_after_commit` - which fixes the *ordering* (a rollback no longer strands a
restored row on a gone file or table) but not the *durability*: the in-process task
is lost the moment the process that queued it dies (#1349). Handing it to a Prefect
deployment run instead makes it survive - the run is recorded on the server, its
parameters are the durable record, and a worker retries it (#1274). The gap none of
this closes is commit-to-dispatch: a crash after the commit but before the run is
submitted still loses the cleanup, which only a record committed *with* the delete
(an outbox) would close.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from prefect import flow
from prefect.deployments import run_deployment
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logging import setup_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.rag.vectorstore import PgVectorStore

logger = logging.getLogger(__name__)

# The Prefect deployment identifier stays `org-purge-cleanup`, the name #1274
# registered, even though the flow it serves is now general: renaming a live
# deployment strands any run still queued under the old name across a rolling
# upgrade - the new process registers only the new name and stops polling the old,
# and the run has no row left to reconstruct it (#1349 review). The Python symbols
# carry the general name; only this external identifier is held put.
_CLEANUP_DEPLOYMENT = "org-purge-cleanup/org-purge-cleanup"

# One run carries at most this many storage paths. A large org - or a large
# collection - can leave tens of thousands of files behind, and a path can be long;
# the whole parameter payload has to stay under Prefect's 512 KiB flow-parameter
# limit, or `run_deployment` rejects the run after the rows that carried the paths
# are already gone (#1274).
_MAX_PATHS_PER_RUN = 500

# The submission is fired after the commit that removed the rows, so a run lost to
# a transient Prefect outage - or to the deployment not being registered yet
# during a rollout - has no row left to reconstruct it and no heartbeat to
# re-dispatch it. So the submission itself is retried before it is given up on; the
# run is idempotent, so a retry that duplicates one accepted-but-unacknowledged is
# safe (#1274).
_SUBMIT_ATTEMPTS = 3
_SUBMIT_BACKOFF_SECONDS = 2.0

# A reservation older than this is treated as stuck. The normal cleanup releases a
# name within seconds of the commit, and even a run exhausting the flow's three
# 30-second retries clears in minutes; an hour is well past both, so a reservation
# that outlives it lost its run to the commit-to-dispatch gap or to a drop that
# fails for good - and its name is blocked with nothing left to reattempt it (#1364).
_RESERVATION_MAX_AGE = timedelta(hours=1)


async def dispatch_external_state_cleanup(
    storage_paths: list[str],
    collections: list[str],
    restamps: list[list[str]] | None = None,
) -> None:
    """Submit a committed delete's external-state cleanup as durable flow runs.

    Each run submits-and-returns (`run_deployment(timeout=0)`): the run is recorded
    on the Prefect server and executed by a worker, so a process that dies after the
    commit no longer takes the cleanup with it - the run and its parameters are the
    durable record, and the flow's own retries re-run it if a worker dies (#1274,
    #1349). Handed to `spawn_after_commit` by its caller, so it runs only once the
    relational teardown has committed.

    The paths are chunked across runs so no run's parameters approach Prefect's
    512 KiB limit. Collections and re-stamps ride the first run only -
    `delete_collection` and `restamp_org_to_untagged` are both idempotent, but
    re-checking them once is enough. The window none of this closes is
    commit-to-dispatch: a crash after the commit but before this fires still loses
    the cleanup, which only a record committed *with* the delete (an outbox) would
    close - a larger change deferred.
    """
    restamps = restamps or []
    chunks = [
        storage_paths[i : i + _MAX_PATHS_PER_RUN]
        for i in range(0, len(storage_paths), _MAX_PATHS_PER_RUN)
    ] or [[]]
    for index, chunk in enumerate(chunks):
        first = index == 0
        await _submit_cleanup_run(chunk, collections if first else [], restamps if first else [])


async def _submit_cleanup_run(
    storage_paths: list[str], collections: list[str], restamps: list[list[str]]
) -> None:
    """One `run_deployment` submission, retried before it is given up on.

    A submission lost for good is a run that never existed, so its file chunk (and,
    on the first run, the table drops) is orphaned with no row to reconstruct it.
    Best-effort past the retries: a chunk that cannot be submitted is logged and the
    remaining chunks still go, rather than one transient failure aborting the rest.

    `restamps` is left out of the parameters when empty - the common purge has none
    - so an ordinary run submits exactly the payload it always did, and only a purge
    that actually orphaned a personal base carries the newer parameter across an
    upgrade (#1684).
    """
    parameters: dict[str, list[str] | list[list[str]]] = {
        "storage_paths": storage_paths,
        "collections": collections,
    }
    if restamps:
        parameters["restamps"] = restamps
    for attempt in range(_SUBMIT_ATTEMPTS):
        try:
            # `run_deployment` is sync-compatible: its stub unions the coroutine it
            # returns in an async context with the `FlowRun` a sync caller gets, and
            # ty cannot tell which applies. Awaiting it is correct here.
            await run_deployment(  # ty: ignore[invalid-await]
                name=_CLEANUP_DEPLOYMENT,
                parameters=parameters,
                timeout=0,
            )
        except Exception:
            if attempt == _SUBMIT_ATTEMPTS - 1:
                logger.exception("external_state_cleanup submission failed after retries")
                return
            await asyncio.sleep(_SUBMIT_BACKOFF_SECONDS * (attempt + 1))
        else:
            return


@asynccontextmanager
async def _vector_store() -> AsyncIterator[PgVectorStore]:
    """A `PgVectorStore` on an engine built for one run and disposed after it.

    A pooled connection made on one flow's event loop breaks on the next, so each run
    that touches vector tables builds and disposes its own engine - the reason
    `rag_tasks._ingestion_service` does too (#948).
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
    restamps: list[list[str]] | None = None,
) -> dict[str, int]:
    """Unlink a committed delete's stored uploads and drop its unreferenced vector tables.

    The cleanup itself, plain async so it is testable without a Prefect runtime
    and reusable by the flow below. Runs after the rows that named this state are
    committed-gone, so the paths and collection names it is handed are all that is
    left of them.

    Idempotent, because the flow's retries must be safe: unlinking a file already gone
    is a no-op, and the drop issues `DROP TABLE IF EXISTS`. The delete path decided
    each name should be dropped and reserved it against reuse (`collection_teardowns`,
    #1362), so a reserved name is dropped whatever now claims it - the reservation
    blocked any legitimate claim. A name with no reservation is a run queued by code
    from before #1362 (an upgrade replaying an old run under the retained deployment
    name), and that one falls back to the reference check so it does not drop a name
    reclaimed since. The drop, the ordered release and the lock live in
    :func:`_drop_then_release`.

    `restamps` are the personal bases an organization purge orphaned: each
    `[collection, org_id, kb_id]` untags that org's rows for that base's own
    surviving documents on a table the base still keeps alive, so its new
    `vector_tenant=None` reaches them again rather than leaving them stranded behind
    the `IS NULL` read scope (#1684). The base's `parent_doc_id`s are resolved here,
    at run time, from `rag_documents` - so a document deleted between the org's
    deletion and this run is no longer among them and its rows are left stamped
    (untagging them would un-delete it) rather than resurrected. Re-stamping is
    idempotent - a table already dropped is a no-op and an absent tag strips to
    nothing - so it is safe under the flow's retries.
    """
    from app.db.locks import LockScope, hold_name
    from app.db.session import get_worker_db_context
    from app.repositories import collection_teardown_repo, knowledge_base_repo, rag_document_repo
    from app.services.file_storage import get_file_storage

    restamps = restamps or []
    storage = get_file_storage()
    for storage_path in storage_paths:
        # Best-effort but not silent: the row that named this file is committed-gone,
        # so a swallowed failure leaves an orphan nothing else can find - the warning
        # is its only remaining trace of which path it was (#1293).
        try:
            await storage.delete(storage_path)
        except Exception as exc:
            logger.warning("Failed to unlink stored file %s: %s", storage_path, exc)

    dropped = 0
    restamped = 0
    if collections or restamps:
        async with _vector_store() as store, get_worker_db_context() as db:
            for collection in collections:
                await hold_name(db, LockScope.COLLECTION_TEARDOWN, collection)
                # A run this code reserved drops unconditionally; a legacy run from
                # before the reservation existed - an upgrade executing an old queued
                # run under the retained deployment name - has no row, so it falls back
                # to the reference check and does not drop a name that was reclaimed
                # since it was queued (#1362 review, #913).
                reserved = await collection_teardown_repo.is_reserved(db, collection)
                if not reserved and await knowledge_base_repo.list_by_collection_name(
                    db, collection
                ):
                    continue
                if await _drop_then_release(store, db, collection):
                    dropped += 1
            for collection, org_id, kb_id in restamps:
                # Best-effort like the drops and unlinks: one bad re-stamp must not
                # abort the rest. The org row that named this state is committed-gone,
                # but the personal base survives, so its current documents say which
                # rows are its own to untag - a document deleted since is already
                # absent here and stays stamped (#1684).
                try:
                    doc_ids = await rag_document_repo.list_vector_document_ids(db, UUID(kb_id))
                    await store.restamp_documents_to_untagged(collection, UUID(org_id), doc_ids)
                except SQLAlchemyError as exc:
                    logger.warning("Failed to re-stamp collection %s: %s", collection, exc)
                else:
                    restamped += 1

    logger.info(
        "external_state_cleanup",
        extra={"unlinked": len(storage_paths), "dropped": dropped, "restamped": restamped},
    )
    return {"unlinked": len(storage_paths), "dropped": dropped, "restamped": restamped}


async def sweep_teardown_reservations() -> dict[str, int]:
    """Reattempt the drop for reservations whose durable cleanup never finished.

    A reservation is committed with its delete and released the instant the drop runs,
    so one older than `_RESERVATION_MAX_AGE` lost its cleanup run to the
    commit-to-dispatch gap or to a drop that fails for good - and blocks its name with
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


# Flow name held at `org-purge-cleanup` deliberately - it is half the deployment
# identifier, and renaming it strands in-flight runs across an upgrade (see
# `_CLEANUP_DEPLOYMENT`). The Python name is general; the Prefect name is not renamed.
@flow(name="org-purge-cleanup", log_prints=True, retries=3, retry_delay_seconds=30)
async def external_state_cleanup_flow(
    storage_paths: list[str],
    collections: list[str],
    restamps: list[list[str]] | None = None,
) -> dict[str, int]:
    """The durable wrapper: what `dispatch_external_state_cleanup` submits.

    Thin over :func:`cleanup_external_state` so the cleanup can be tested without a
    Prefect runtime. The `@flow` is what carries the durability - the run and its
    parameters are recorded on the Prefect server, and `retries` re-run it on a
    worker if it or the process it was dispatched from dies (#1274, #1349).

    `restamps` defaults to `None` so a run queued before it existed - an upgrade
    replaying an old run under the retained deployment name - still binds (#1684).
    """
    setup_logging()
    return await cleanup_external_state(storage_paths, collections, restamps)


@flow(name="teardown-reservation-sweep", log_prints=True)
async def teardown_reservation_sweep_flow() -> dict[str, int]:
    """Scheduled sweep: reattempt the drop for reservations whose cleanup was lost.

    Thin over :func:`sweep_teardown_reservations` so it can be tested without a Prefect
    runtime. No `retries`: the next hourly tick is the retry, and a reservation stuck
    long enough to be swept is by definition not urgent (#1364).
    """
    setup_logging()
    return await sweep_teardown_reservations()
