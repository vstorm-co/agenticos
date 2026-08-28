"""Durable teardown of a deleted organization's external state.

`OrganizationService.purge` commits the relational teardown of an organization -
its rows, its knowledge bases, its document records - and then hands the external
side effects, unlinking the stored uploads and dropping the vector tables, to
this flow. Handing them over rather than running them in the request process is
what makes them survive: the run is recorded on the Prefect server and retried by
a worker, where the in-process `spawn_after_commit` task it replaces was lost the
moment the process that dispatched it died (#1274).
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

_ORG_PURGE_DEPLOYMENT = "org-purge-cleanup/org-purge-cleanup"

# One run carries at most this many storage paths. A large org can leave tens of
# thousands of files behind, and a path can be long; the whole parameter payload
# has to stay under Prefect's 512 KiB flow-parameter limit, or `run_deployment`
# rejects the run after the rows that carried the paths are already gone (#1274).
_MAX_PATHS_PER_RUN = 500

# The submission is fired after the commit that removed the rows, so a run lost to
# a transient Prefect outage - or to the deployment not being registered yet
# during a rollout - has no row left to reconstruct it and no heartbeat to
# re-dispatch it. So the submission itself is retried before it is given up on; the
# run is idempotent, so a retry that duplicates one accepted-but-unacknowledged is
# safe (#1274).
_SUBMIT_ATTEMPTS = 3
_SUBMIT_BACKOFF_SECONDS = 2.0


async def dispatch_org_purge_cleanup(storage_paths: list[str], collections: list[str]) -> None:
    """Submit an org's external-state cleanup as durable flow runs, and return.

    Each run submits-and-returns (`run_deployment(timeout=0)`): the run is recorded
    on the Prefect server and executed by a worker, so a process that dies after the
    commit no longer takes the cleanup with it - the run and its parameters are the
    durable record, and the flow's own retries re-run it if a worker dies (#1274).
    Handed to `spawn_after_commit` by `OrganizationService.purge`, so it runs only
    once the relational teardown has committed.

    The paths are chunked across runs so no run's parameters approach Prefect's
    512 KiB limit. Collections ride the first run only - `delete_collection` is
    idempotent, but re-checking them once is enough. The window none of this closes
    is commit-to-dispatch: a crash after the commit but before this fires still
    loses the cleanup, which only a record committed *with* the delete (an outbox)
    would close - a larger change #1274 deferred.
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
                name=_ORG_PURGE_DEPLOYMENT,
                parameters={"storage_paths": storage_paths, "collections": collections},
                timeout=0,
            )
        except Exception:
            if attempt == _SUBMIT_ATTEMPTS - 1:
                logger.exception("org_purge_cleanup submission failed after retries")
                return
            await asyncio.sleep(_SUBMIT_BACKOFF_SECONDS * (attempt + 1))
        else:
            return


async def purge_org_external_state(
    storage_paths: list[str], collections: list[str]
) -> dict[str, int]:
    """Unlink a purged org's stored uploads and drop its unreferenced vector tables.

    The cleanup itself, plain async so it is testable without a Prefect runtime
    and reusable by the flow below. Runs after the org's rows are committed-gone,
    so the paths and collection names it is handed are all that is left of them.

    Idempotent, because the flow's retries must be safe: unlinking a file already
    gone is a no-op, `delete_collection` issues `DROP TABLE IF EXISTS`, and each
    collection is re-checked against the knowledge-base table so a name a second
    org has claimed since the purge keeps its table (#913). The store rides an
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
        with contextlib.suppress(Exception):
            await storage.delete(storage_path)

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

    logger.info("org_purge_cleanup", extra={"unlinked": len(storage_paths), "dropped": dropped})
    return {"unlinked": len(storage_paths), "dropped": dropped}


@flow(name="org-purge-cleanup", log_prints=True, retries=3, retry_delay_seconds=30)
async def org_purge_cleanup_flow(
    storage_paths: list[str], collections: list[str]
) -> dict[str, int]:
    """The durable wrapper: what `dispatch_org_purge_cleanup` submits.

    Thin over :func:`purge_org_external_state` so the cleanup can be tested
    without a Prefect runtime. The `@flow` is what carries the durability - the
    run and its parameters are recorded on the Prefect server, and `retries` re-run
    it on a worker if it or the process it was dispatched from dies (#1274).
    """
    setup_logging()
    return await purge_org_external_state(storage_paths, collections)
