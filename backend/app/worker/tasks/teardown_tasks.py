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
import contextlib
import logging

from prefect import flow
from prefect.deployments import run_deployment
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logging import setup_logging

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


async def dispatch_external_state_cleanup(storage_paths: list[str], collections: list[str]) -> None:
    """Submit a committed delete's external-state cleanup as durable flow runs.

    Each run submits-and-returns (`run_deployment(timeout=0)`): the run is recorded
    on the Prefect server and executed by a worker, so a process that dies after the
    commit no longer takes the cleanup with it - the run and its parameters are the
    durable record, and the flow's own retries re-run it if a worker dies (#1274,
    #1349). Handed to `spawn_after_commit` by its caller, so it runs only once the
    relational teardown has committed.

    The paths are chunked across runs so no run's parameters approach Prefect's
    512 KiB limit. Collections ride the first run only - `delete_collection` is
    idempotent, but re-checking them once is enough. The window none of this closes
    is commit-to-dispatch: a crash after the commit but before this fires still
    loses the cleanup, which only a record committed *with* the delete (an outbox)
    would close - a larger change deferred.
    """
    chunks = [
        storage_paths[i : i + _MAX_PATHS_PER_RUN]
        for i in range(0, len(storage_paths), _MAX_PATHS_PER_RUN)
    ] or [[]]
    for index, chunk in enumerate(chunks):
        await _submit_cleanup_run(chunk, collections if index == 0 else [])


async def _submit_cleanup_run(storage_paths: list[str], collections: list[str]) -> None:
    """One `run_deployment` submission, retried before it is given up on.

    A submission lost for good is a run that never existed, so its file chunk (and,
    on the first run, the table drops) is orphaned with no row to reconstruct it.
    Best-effort past the retries: a chunk that cannot be submitted is logged and the
    remaining chunks still go, rather than one transient failure aborting the rest.
    """
    for attempt in range(_SUBMIT_ATTEMPTS):
        try:
            # `run_deployment` is sync-compatible: its stub unions the coroutine it
            # returns in an async context with the `FlowRun` a sync caller gets, and
            # ty cannot tell which applies. Awaiting it is correct here.
            await run_deployment(  # ty: ignore[invalid-await]
                name=_CLEANUP_DEPLOYMENT,
                parameters={"storage_paths": storage_paths, "collections": collections},
                timeout=0,
            )
        except Exception:
            if attempt == _SUBMIT_ATTEMPTS - 1:
                logger.exception("external_state_cleanup submission failed after retries")
                return
            await asyncio.sleep(_SUBMIT_BACKOFF_SECONDS * (attempt + 1))
        else:
            return


async def cleanup_external_state(
    storage_paths: list[str], collections: list[str]
) -> dict[str, int]:
    """Unlink a committed delete's stored uploads and drop its unreferenced vector tables.

    The cleanup itself, plain async so it is testable without a Prefect runtime
    and reusable by the flow below. Runs after the rows that named this state are
    committed-gone, so the paths and collection names it is handed are all that is
    left of them.

    Idempotent, because the flow's retries must be safe: unlinking a file already
    gone is a no-op, `delete_collection` issues `DROP TABLE IF EXISTS`, and each
    collection is re-checked against the knowledge-base table so a name a second
    org has claimed since the delete keeps its table (#913). The store rides an
    engine built for this one run and disposed on the way out, because a pooled
    connection made on one flow's event loop breaks the next (the reason
    `rag_tasks._ingestion_service` builds per-flow engines too, #948).
    """
    from app.db.session import get_worker_db_context
    from app.repositories import knowledge_base_repo
    from app.services.embedding_resolution import embeddings_for_collection
    from app.services.file_storage import get_file_storage
    from app.services.rag.embeddings import EmbeddingService
    from app.services.rag.vectorstore import PgVectorStore

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
    if collections:
        rag_settings = settings.rag
        engine = create_async_engine(settings.DATABASE_URL)
        try:
            store = PgVectorStore(
                settings=rag_settings,
                embedding_service=EmbeddingService(settings=rag_settings),
                resolver=embeddings_for_collection,
                engine=engine,
            )
            async with get_worker_db_context() as db:
                for collection in collections:
                    if await knowledge_base_repo.list_by_collection_name(db, collection):
                        continue
                    with contextlib.suppress(SQLAlchemyError):
                        await store.delete_collection(collection)
                        dropped += 1
        finally:
            await engine.dispose()

    logger.info(
        "external_state_cleanup", extra={"unlinked": len(storage_paths), "dropped": dropped}
    )
    return {"unlinked": len(storage_paths), "dropped": dropped}


# Flow name held at `org-purge-cleanup` deliberately - it is half the deployment
# identifier, and renaming it strands in-flight runs across an upgrade (see
# `_CLEANUP_DEPLOYMENT`). The Python name is general; the Prefect name is not renamed.
@flow(name="org-purge-cleanup", log_prints=True, retries=3, retry_delay_seconds=30)
async def external_state_cleanup_flow(
    storage_paths: list[str], collections: list[str]
) -> dict[str, int]:
    """The durable wrapper: what `dispatch_external_state_cleanup` submits.

    Thin over :func:`cleanup_external_state` so the cleanup can be tested without a
    Prefect runtime. The `@flow` is what carries the durability - the run and its
    parameters are recorded on the Prefect server, and `retries` re-run it on a
    worker if it or the process it was dispatched from dies (#1274, #1349).
    """
    setup_logging()
    return await cleanup_external_state(storage_paths, collections)
