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
from datetime import timedelta
from uuid import UUID

from prefect import flow
from prefect.deployments import run_deployment
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logging import setup_logging
from app.db.session import get_worker_db_context
from app.repositories import teardown_intent_repo

logger = logging.getLogger(__name__)

_ORG_PURGE_DEPLOYMENT = "org-purge-cleanup/org-purge-cleanup"

# The submission is fired after the commit that removed the rows. A submission
# lost to a transient Prefect outage - or to the deployment not being registered
# yet during a rollout - is retried here, and if it still fails the intent row is
# left undispatched for the sweep to find. The run is idempotent, so a retry that
# duplicates one accepted-but-unacknowledged is safe (#1274).
_SUBMIT_ATTEMPTS = 3
_SUBMIT_BACKOFF_SECONDS = 2.0

# How long a dispatched intent may sit before the sweep assumes its run is not
# coming back. Generously past the flow's own three retries at thirty seconds,
# so a healthy run is never duplicated by impatience.
_STALE_AFTER = timedelta(minutes=15)

# One sweep re-dispatches at most this many. A backlog is drained over several
# ticks rather than in one burst that floods the work queue.
_SWEEP_BATCH = 50


async def dispatch_org_purge_cleanup(intent_id: UUID) -> None:
    """Hand one recorded teardown to a worker, and stamp that it was handed over.

    The parameter is an id rather than the paths and collections themselves, and
    that is what removed the chunking this used to do: a large org can leave tens
    of thousands of files behind, and the whole payload had to stay under
    Prefect's 512 KiB flow-parameter limit. The flow reads them from the row.

    Handed to `spawn_after_commit` by `OrganizationService.purge`, so it runs only
    once the relational teardown - and the intent beside it - has committed.
    Failing here is no longer fatal: the row stays undispatched and
    :func:`teardown_sweep_flow` picks it up.
    """
    if not await _submit_cleanup_run(intent_id):
        logger.warning(
            "org_purge_cleanup not dispatched; leaving intent %s for the sweep", intent_id
        )
        return
    async with get_worker_db_context() as db:
        await teardown_intent_repo.mark_dispatched(db, intent_id)


async def _submit_cleanup_run(intent_id: UUID) -> bool:
    """One `run_deployment` submission, retried before it is given up on."""
    for attempt in range(_SUBMIT_ATTEMPTS):
        try:
            # `run_deployment` is sync-compatible: its stub unions the coroutine it
            # returns in an async context with the `FlowRun` a sync caller gets, and
            # ty cannot tell which applies. Awaiting it is correct here.
            await run_deployment(  # ty: ignore[invalid-await]
                name=_ORG_PURGE_DEPLOYMENT,
                parameters={"intent_id": str(intent_id)},
                timeout=0,
            )
        except Exception:
            if attempt == _SUBMIT_ATTEMPTS - 1:
                logger.exception("org_purge_cleanup submission failed after retries")
                return False
            await asyncio.sleep(_SUBMIT_BACKOFF_SECONDS * (attempt + 1))
        else:
            return True
    return False


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
async def org_purge_cleanup_flow(intent_id: str) -> dict[str, int]:
    """The durable wrapper: what `dispatch_org_purge_cleanup` submits.

    Reads what to release from the intent row rather than from its parameters,
    and deletes the row once it is released - which is how the work records that
    it is done. An intent already gone is a run that has already succeeded, or a
    duplicate of one; either way there is nothing to do and nothing to complain
    about (#1269).

    The `@flow` carries the durability of the run itself - recorded on the
    Prefect server, `retries` re-running it on a worker if one dies (#1274). The
    row carries the durability of the *intent*, which is what survives a crash
    before this was ever submitted.
    """
    setup_logging()
    async with get_worker_db_context() as db:
        intent = await teardown_intent_repo.get(db, UUID(intent_id))
        if intent is None:
            logger.info("teardown intent %s is already finished", intent_id)
            return {"unlinked": 0, "dropped": 0}
        storage_paths = list(intent.storage_paths)
        collections = list(intent.collections)

    released = await purge_org_external_state(storage_paths, collections)

    async with get_worker_db_context() as db:
        await teardown_intent_repo.finish(db, UUID(intent_id))
        await db.commit()
    return released


@flow(name="teardown-sweep", log_prints=True)
async def teardown_sweep_flow() -> dict[str, int]:
    """Re-dispatch the teardowns nothing finished.

    The half `spawn_after_commit` cannot cover: a process that died between the
    purge's commit and the hand-off leaves an intent nobody ever submitted, and
    the committed delete has already removed the paths and collection names a
    retry would otherwise need to find (#1269).

    Two shapes are claimed - never dispatched, and dispatched long enough ago
    that the run is not coming back - because from here they are the same
    problem. Dispatching one twice costs a wasted run; not dispatching it costs
    an orphaned table and files nothing in the database names.
    """
    setup_logging()
    async with get_worker_db_context() as db:
        stale = await teardown_intent_repo.claim_stale(
            db, older_than=_STALE_AFTER, limit=_SWEEP_BATCH
        )
        ids = [intent.id for intent in stale]
        await db.commit()

    dispatched = 0
    for intent_id in ids:
        if await _submit_cleanup_run(intent_id):
            dispatched += 1

    if ids:
        logger.info("teardown_sweep", extra={"claimed": len(ids), "dispatched": dispatched})
    return {"claimed": len(ids), "dispatched": dispatched}
