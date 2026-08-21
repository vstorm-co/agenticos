"""RAG ingestion & sync tasks - processes documents asynchronously."""

import asyncio
import hashlib
import json
import logging
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from prefect import flow, get_run_logger
from prefect.exceptions import MissingContextError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import BudgetExceeded, SpendLedger, metered_by
from app.core.config import settings
from app.core.secret_kinds import SecretKind, StorableSecret, unseal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus
from app.db.session import get_worker_db_context
from app.repositories import ingestion_spend_repo, knowledge_base_repo, organization_secret_repo
from app.repositories import sync_source as sync_source_repo
from app.services.embedding_resolution import (
    ResolvedEmbeddings,
    embeddings_for_collection,
)
from app.services.ingestion_config import (
    IngestionConfig,
    IngestionConfigService,
    deployment_defaults,
)
from app.services.rag.config import DocumentExtensions
from app.services.rag.connectors import CONNECTOR_REGISTRY
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.failures import IngestionStage, failure_summary
from app.services.rag.ingestion import IngestionService, StoredDocument
from app.services.rag.models import IngestionResult, IngestionStatus
from app.services.rag.vectorstore import EmbeddingResolver
from app.services.rag.vectorstore import PgVectorStore as VectorStore
from app.services.spend import assert_organization_within_budget
from app.services.sync_source import SyncSourceService

logger = logging.getLogger(__name__)


def _say_in_flow_log(message: str) -> None:
    """Put one line where the operator of a failing ingestion is looking.

    Prefect ships a run's log to the UI through the logger `get_run_logger`
    hands out; a `logging` call from a library module goes to the worker's
    stdout and no further. Outside a run there is no such logger, and this is
    still a plain module function - a direct CLI ingest, or a test - so the
    module logger is the fallback rather than a crash on a log line.
    """
    try:
        get_run_logger().warning(message)
    except MissingContextError:
        logger.warning(message)


def _announcing_resolver() -> EmbeddingResolver:
    """`embeddings_for_collection`, saying a degraded credential out loud once.

    The resolver falls back to the deployment key on three paths - the chosen
    secret deleted, unsealable, or not an API key - each a `logger.warning` in
    `app.services.embedding_resolution` that reaches nothing an operator reads.
    So a collection that *had* been given a vault key either failed with advice
    about a deployment variable, or succeeded while billing the deployment's
    account, and in both cases nothing said which of the three had happened.

    Two things it does not say. A collection that simply chose no key: that is
    the documented normal path. And the same collection twice - the store
    resolves per operation rather than per cache miss, so indexing one document
    asks twice (once to create the table, once to embed), and a sync of two
    hundred files would otherwise print four hundred copies of the line it
    exists to make noticeable. The set is per ingestion service, so it is per
    flow run rather than per process; a credential fixed between runs is
    reported again on the next one.
    """
    announced: set[str] = set()

    async def resolve(
        collection_name: str, organization_id: UUID | None
    ) -> ResolvedEmbeddings | None:
        resolved = await embeddings_for_collection(collection_name, organization_id)
        if (
            resolved is not None
            and resolved.key_source.is_degraded
            and collection_name not in announced
        ):
            announced.add(collection_name)
            _say_in_flow_log(f"Embedding {resolved.describe(collection_name)}.")
        return resolved

    return resolve


async def _ingestion_service_for(
    db: AsyncSession,
    *,
    config: IngestionConfig,
    organization_id: UUID | None,
) -> IngestionService:
    """An ingester that reads documents the way the collection asked to be read.

    Both halves come off the collection. The parser, the chunker and the image
    model come from its `IngestionConfig`; the embedding model, its recorded
    vector width and the vault key that pays for it come from the resolver,
    which the store consults per collection.

    That resolver used to be omitted here, and only here - the deployment's
    model and `OPENROUTER_API_KEY` were used for every collection, whatever it
    had chosen. On a deployment with no key set that was a crash advising the
    operator to set one; with both set it was worse, because the embeddings
    were billed to the deployment while the product said the organization's
    key paid (#306).

    An earlier version of this docstring said the model was fixed per
    deployment and that "the check that the two still agree happens before an
    upload is accepted". No such check exists, and none should: since
    per-collection resolution landed, a collection keeps embedding with the
    model it was built with whatever the deployment default became, which is
    the point of recording it. What *is* checked before an upload is accepted
    is `IngestionConfigService.check_embedding_model` - that this build knows a
    width for the collection's model at all, because vectors it cannot produce
    would fail in a worker with nothing on screen.
    """
    rag_settings = settings.rag
    # The processor first: it is the part that can fail, and a store built before
    # it would be a pool nobody holds a reference to (#948).
    processor = await IngestionConfigService(db).build_processor(organization_id, config)
    vector_store = VectorStore(
        settings=rag_settings,
        embedding_service=EmbeddingService(settings=rag_settings),
        resolver=_announcing_resolver(),
    )
    return IngestionService(
        processor=processor, vector_store=vector_store, organization_id=organization_id
    )


async def _record_embedding_spend(
    ledger: SpendLedger, *, organization_id: UUID | None, rag_document_id: UUID | None
) -> None:
    """Persist what a metering window spent, if it spent anything.

    One row per model per window - a document upload, a whole sync - rather
    than per API call: the unit anyone reconciles against a bill is "what did
    indexing this cost with which model", and a window can spend in two models
    at once - the embedder and the image describer. Written even when the
    window failed, because a document that died half-embedded still spent the
    tokens it got through, and a budget that ignores failures is not a budget.
    """
    if not ledger.entries:
        return
    async with get_worker_db_context() as db:
        for model_name in dict.fromkeys(entry.model_name for entry in ledger.entries):
            entries = [entry for entry in ledger.entries if entry.model_name == model_name]
            await ingestion_spend_repo.record(
                db,
                organization_id=organization_id,
                rag_document_id=rag_document_id,
                model=model_name,
                input_tokens=sum(entry.input_tokens for entry in entries),
                output_tokens=sum(entry.output_tokens for entry in entries),
                cost_usd=sum((entry.cost_usd for entry in entries), Decimal(0)),
                cost_is_partial=any(not entry.priced for entry in entries),
            )


async def _knowledge_base_for(
    db: AsyncSession, collection_name: str | None, organization_id: UUID | None
) -> KnowledgeBase | None:
    """The knowledge base behind a collection name, or `None` if none claims it.

    The organization narrows the candidates because `collection_name` is not
    unique across tenants - and the caller's own row wins over a deployment-wide
    one of the same name, which is the reason for two passes rather than one
    condition.

    An `app`-scoped collection belongs to no organization, so it is matched on
    the second pass rather than skipped. Skipping it meant a source pointed at
    one was parsed with the deployment defaults instead of the settings that
    collection had chosen, and - once a sync started recording documents - filed
    them under no knowledge base, which is the invisibility this was fixing
    (#992).

    Two callers still reach `None`: a local-directory sync, which names a path on
    the server rather than a collection somebody configured, and a sync source
    with no collection at all - an org-level integration template that exists to
    be cloned and should never have been run.
    """
    if collection_name is None:
        return None
    return await knowledge_base_repo.get_for_collection(db, collection_name, organization_id)


async def _config_for_collection(
    db: AsyncSession, collection_name: str | None, organization_id: UUID | None
) -> IngestionConfig:
    """The configuration of the knowledge base behind a collection name.

    A sync writes into a collection the same way an upload does, so it has to
    read documents the same way too - a collection set to LiteParse that gets
    PyMuPDF whenever the file arrives from Google Drive is configured in name
    only.

    Falls back to the deployment defaults when no knowledge base claims the
    name; `_knowledge_base_for` says which callers that is.
    """
    kb = await _knowledge_base_for(db, collection_name, organization_id)
    return (
        deployment_defaults() if kb is None else IngestionConfig.model_validate(kb.ingestion_config)
    )


@flow(name="ingest-document", log_prints=True)
async def ingest_document_flow(
    rag_document_id: str,
    collection_name: str,
    filepath: str,
    source_path: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Process a document: parse, chunk, embed, store in vector DB.

    The row this puts an error on is read on the documents page, so what lands
    there is a summary rather than the exception's own text (#423). The text
    itself is in this flow's log twice over - the line below, and the traceback
    Prefect records because the failure is re-raised.
    """
    logger.info("Starting ingestion: %s -> %s", source_path, collection_name)
    try:
        return await _run_ingestion(
            rag_document_id, collection_name, filepath, source_path, replace
        )
    except Exception as exc:
        logger.exception("Ingestion failed for %s", source_path)
        await _fail_document(
            rag_document_id,
            error_message=failure_summary(exc, stage=IngestionStage.INGEST),
        )
        raise


@flow(name="sync-collection", log_prints=True)
async def sync_collection_flow(
    sync_log_id: str, source: str, collection_name: str, mode: str, path: str
) -> dict[str, Any]:
    """Sync a collection from a local directory."""
    logger.info("Starting sync: %s -> %s (mode=%s)", source, collection_name, mode)
    try:
        return await _run_sync(sync_log_id, source, collection_name, mode, path)
    except Exception as exc:
        logger.exception("Sync failed for %s -> %s", source, collection_name)
        await _update_sync_log(
            sync_log_id, "error", error_message=failure_summary(exc, stage=IngestionStage.SYNC)
        )
        raise


@flow(name="sync-single-source", log_prints=True)
async def sync_single_source_flow(source_id: str, sync_log_id: str | None = None) -> dict[str, Any]:
    """Sync a single connector source. If sync_log_id provided, use existing log."""
    logger.info("Starting source sync: %s", source_id)
    return await _run_source_sync(source_id, sync_log_id=sync_log_id)


@flow(name="rag-sync-check", log_prints=True)
async def check_scheduled_syncs_flow() -> None:
    """Scheduled flow: find sources due for sync and dispatch individual flows."""
    async with get_worker_db_context() as db:
        sources = await sync_source_repo.get_due_for_sync(db)
        tasks = [asyncio.create_task(sync_single_source_flow(str(source.id))) for source in sources]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Scheduled sync check: dispatched %d source(s)", len(sources))


async def _run_ingestion(
    rag_document_id: str, collection_name: str, filepath: str, source_path: str, replace: bool
) -> dict[str, Any]:
    """Parse and index one uploaded document, exactly as its record says to.

    The configuration comes off the `rag_documents` row rather than out of the
    environment, and it is the *resolved* one - the collection's, with whatever
    that upload overrode already folded in. Reading the collection again here
    would quietly re-parse with settings that changed while the file waited in
    the queue, and would lose the override entirely.
    """
    from app.services.rag_document import RAGDocumentService

    async with get_worker_db_context() as db:
        record = await RAGDocumentService(db).get_document(rag_document_id)
        organization_id = record.organization_id
        # Checked again here, not only at upload: the budget can be reached by
        # runs that finished while this file waited in the queue. Raising lets
        # the flow's handler put the refusal on the document row, where the
        # uploader will look for it.
        if organization_id is not None:
            await assert_organization_within_budget(db, organization_id)
        config = IngestionConfig.model_validate(record.ingestion_config)
        ingestion_service = await _ingestion_service_for(
            db, config=config, organization_id=organization_id
        )

    ledger = SpendLedger(organization_id=organization_id)
    file_path = Path(filepath)
    try:
        with metered_by(ledger):
            result = await ingestion_service.ingest_file(
                filepath=file_path,
                collection_name=collection_name,
                replace=replace,
                source_path=source_path,
            )
    except Exception as exc:
        # `ingest_file` reports a failed parse or a failed index by returning
        # one, so what reaches here escaped the metering window instead - the
        # budget, or the pipeline itself. Which stage it was is not knowable
        # from here, and the stage below says so.
        logger.exception("Ingestion failed for %s", source_path)
        await _fail_document(
            rag_document_id,
            error_message=failure_summary(exc, stage=IngestionStage.INGEST),
        )
        raise
    finally:
        # The store owns a pooled engine, and one flow runs per uploaded
        # document, so a store left behind leaves its pool open for the life of
        # the worker process (#948).
        await ingestion_service.store.aclose()
        await _record_embedding_spend(
            ledger, organization_id=organization_id, rag_document_id=UUID(rag_document_id)
        )

    # Checked outside the `try` because `ingest_file` *returns* a failure rather
    # than raising one - which is why this used to fall straight through to
    # `complete_ingestion` below. A document whose embeddings were never written
    # was marked `done`, and that is worse than an error: the collection looks
    # ingested, answers nothing, and says nowhere why. Reproduced with no
    # embedding credential configured - the service logged an accurate refusal,
    # the flow finished `Completed()`, the row said `done`, and the vector table
    # held zero rows.
    if result.status is not IngestionStatus.DONE:
        reason = result.error_message or result.message
        await _fail_document(rag_document_id, error_message=reason)
        raise RuntimeError(f"Ingestion failed for {source_path}: {reason}")

    try:
        async with get_worker_db_context() as db:
            await RAGDocumentService(db).complete_ingestion(
                rag_document_id,
                vector_document_id=result.document_id,
                chunk_count=result.chunk_count,
                replaced_document_id=result.replaced_document_id,
            )
    except Exception as exc:
        logger.exception("Indexed %s but could not record it", source_path)
        await _fail_document(
            rag_document_id,
            error_message=failure_summary(exc, stage=IngestionStage.RECORD),
        )
        raise

    logger.info("Ingestion complete: %s", source_path)
    return {"status": "done", "document_id": result.document_id, "filename": source_path}


async def _run_sync(
    sync_log_id: str, source: str, collection_name: str, mode: str, path: str
) -> dict[str, Any]:
    from app.services.rag_sync import RAGSyncService

    target_path = Path(path).resolve()
    if not target_path.exists():
        await _update_sync_log(sync_log_id, "error", error_message=f"Path not found: {path}")
        return {"status": "error", "message": f"Path not found: {path}"}

    if target_path.is_file():
        files = [target_path]
    else:
        files = [f for f in target_path.rglob("*") if f.is_file() and not f.name.startswith(".")]

    allowed = {ext.value for ext in DocumentExtensions}
    files = [f for f in files if f.suffix.lower() in allowed]
    ingested = updated = skipped = failed = 0

    # No tenant: a local-directory sync names a path on the server, not a
    # collection somebody's organization owns. The spend is still recorded -
    # with no organization to bill - because a total that quietly under-reports
    # is worse than one holding rows nobody claims.
    ledger = SpendLedger()

    # Built after the validations above, and disposed in the `finally` below: the
    # store owns a pooled engine, so one built before an early return is a pool
    # nothing ever closes (#948).
    async with get_worker_db_context() as db:
        # Kept, not just passed through: every row this sync writes records which
        # parser read the document, and the rows used to carry no configuration at
        # all - so `parser` read `null` for every locally-synced file (#997).
        ingestion_config = await _config_for_collection(db, collection_name, None)
        ingestion_service = await _ingestion_service_for(
            db, config=ingestion_config, organization_id=None
        )

    try:
        for filepath in files:
            async with get_worker_db_context() as db:
                sync_log_check = await RAGSyncService(db).get_sync_log(sync_log_id)
                if sync_log_check.status == "cancelled":
                    logger.info("Sync %s cancelled by user", sync_log_id)
                    await _record_embedding_spend(
                        ledger, organization_id=None, rag_document_id=None
                    )
                    return {
                        "status": "cancelled",
                        "ingested": ingested,
                        "updated": updated,
                        "skipped": skipped,
                        "failed": failed,
                    }

            source_path = str(filepath.resolve())
            if mode in ("new_only", "update_only"):
                # One scan for both answers. They are facts about the same
                # document, and asking for them separately is what let a live
                # file's hash be compared against a different document's (#548).
                existing = await ingestion_service.existing_document(collection_name, source_path)

                if mode == "new_only":
                    if existing.document_id:
                        file_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
                        if existing.content_hash and file_hash == existing.content_hash:
                            skipped += 1
                            continue

                elif mode == "update_only":
                    if not existing.document_id:
                        skipped += 1
                        continue
                    file_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
                    if existing.content_hash and file_hash == existing.content_hash:
                        skipped += 1
                        continue
            try:
                # Opened before the ingest, as the upload and the connector sync
                # do (#992). Written afterwards it could fail afterwards - a
                # database blip, a name longer than the column - leaving the
                # vector document stored and untracked, and the next `new_only`
                # run then matched its unchanged hash and skipped the file before
                # reaching the write, for good (#997).
                row_id = await _open_document_row(
                    filename=filepath.name,
                    filesize=filepath.stat().st_size,
                    collection_name=collection_name,
                    # The same address it hands `existing_document` above, so the
                    # row and the lookup name one file (#996).
                    source_path=source_path,
                    # A path on the server belongs to no tenant and to no
                    # knowledge base; `POST /rag/sync/local` is the one route
                    # that still carries `is_app_admin` for exactly that reason.
                    organization_id=None,
                    knowledge_base_id=None,
                    ingestion_config=ingestion_config,
                    image_description_model=None,
                    embedding_model=None,
                )

                with metered_by(ledger):
                    result = await ingestion_service.ingest_file(
                        filepath=filepath,
                        collection_name=collection_name,
                        replace=True,
                        # The address this flow already looks documents up by. It
                        # was omitted, so the stored document identified itself by
                        # filename while the lookup asked for a path - the
                        # `existing_document` call above only ever matched through
                        # the filename fallback, and the row and the vector would
                        # now disagree about which file this is (#996).
                        source_path=source_path,
                    )

                # Either way, which is the other half of #997: a file that failed
                # to parse used to leave no row and no reason, so a sync log
                # saying four of forty failed named none of the four.
                await _settle_document_row(row_id, result)

                if result.status is IngestionStatus.DONE:
                    if result.replaced_document_id:
                        updated += 1
                    else:
                        ingested += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning("Sync file error %s: %s", filepath.name, e)
                failed += 1

        await _record_embedding_spend(ledger, organization_id=None, rag_document_id=None)

        async with get_worker_db_context() as db:
            await RAGSyncService(db).complete_sync(
                sync_log_id,
                status="done" if failed == 0 else "error",
                total_files=len(files),
                ingested=ingested,
                updated=updated,
                skipped=skipped,
                failed=failed,
            )

        return {
            "status": "done",
            "ingested": ingested,
            "updated": updated,
            "skipped": skipped,
            "failed": failed,
        }
    finally:
        await ingestion_service.store.aclose()


async def _fail_document(rag_document_id: str, *, error_message: str | None) -> None:
    """Put a failure on the document row, and let the first one keep it.

    One collapse is reported by up to three handlers here: the stage that
    raised, the check that a *returned* failure is not `done`, and the flow's
    own backstop - and they run innermost first. The innermost is the specific
    one ("could not be indexed, check the collection's embedding credential");
    the outermost only knows the ingest failed. Overwriting therefore replaces
    the useful sentence with the vague one, which mattered from the moment the
    column stopped holding the same `str(exc)` at every level (#423).

    Failure is the only status this records. Reaching `DONE` needs the vector
    document's id, which only `_run_ingestion` holds, so it calls
    `complete_ingestion` itself.
    """
    from app.services.rag_document import RAGDocumentService

    try:
        async with get_worker_db_context() as db:
            doc_svc = RAGDocumentService(db)
            if (await doc_svc.get_document(rag_document_id)).status == DocumentStatus.ERROR:
                return
            await doc_svc.fail_ingestion(
                rag_document_id, error_message=error_message or "Unknown error"
            )
    except Exception as e:
        logger.warning("Failed to record the ingestion failure: %s", e)


async def _update_sync_log(sync_log_id: str, status: str, error_message: str | None = None) -> None:
    from app.services.rag_sync import RAGSyncService

    try:
        async with get_worker_db_context() as db:
            await RAGSyncService(db).complete_sync(
                sync_log_id, status=status, error_message=error_message
            )
    except Exception as e:
        logger.warning("Failed to update SyncLog: %s", e)


async def _connector_credential(
    db: AsyncSession, secret_id: UUID | None, organization_id: UUID
) -> StorableSecret | None:
    """The unsealed credential a sync source names, or `None`.

    Both ids arrive as `uuid.UUID` - `get_source` answers with the model, whose
    columns are `PG_UUID(as_uuid=True)` - so nothing here re-parses them. Passing
    one to `UUID()` raises `AttributeError: 'UUID' object has no attribute
    'replace'`, which is what this did before review and what a fixture holding a
    string instead of a UUID hid.

    `None` for three reasons, and the connector treats them alike because a
    caller cannot act on the difference: the source names no credential, the
    secret was deleted from the vault (the column is `ON DELETE SET NULL`), or
    the envelope will not open. What must *not* happen is a fallback - a Drive or
    S3 source that ran on the deployment's own credentials would read under the
    operator's identity rather than the tenant's, which is the reach both
    connectors had their environment fallbacks removed for.

    The unsealing happens here rather than in the connector because only this
    layer has a database session, and because a connector that could reach the
    vault could reach another organization's row in it.
    """
    if secret_id is None:
        return None
    row = await organization_secret_repo.get(db, secret_id, organization_id=organization_id)
    if row is None:
        logger.warning("sync_source_secret_missing", extra={"organization": str(organization_id)})
        return None
    try:
        return unseal_secret(
            row.sealed_secret,
            kind=SecretKind(row.kind),
            scope=VaultScope.organization(organization_id),
            key_version=row.key_version,
        )
    except Exception:
        logger.warning("sync_source_secret_unusable", extra={"secret": str(row.id)})
        return None


async def _open_document_row(
    *,
    filename: str,
    filesize: int,
    collection_name: str,
    source_path: str,
    organization_id: UUID | None,
    knowledge_base_id: UUID | None,
    ingestion_config: IngestionConfig,
    image_description_model: str | None,
    embedding_model: str | None,
) -> str:
    """Record a document a sync is about to ingest, and answer its row id.

    A connector sync used to create no `rag_documents` row at all, so its
    documents were searchable and invisible: absent from the knowledge base's
    Documents tab, from a collection's own `document_count`, and from delete -
    a file ingested from a Drive folder could be removed only by dropping the
    whole collection (#992). A failure was counted in the sync log and recorded
    nowhere per-file, so "which four of the forty failed, and why" had no answer.

    No original is stored, unlike an upload, and that holds for both callers:
    a connector's file lives in the system it was synced from and a local one is
    already on this host's disk at the path the sync named, so keeping a second
    copy to make a retry button work is a cost per corpus rather than per
    failure. `has_file` is false for these, and **re-running the sync is the
    retry** - which since #990 skips everything unchanged and re-fetches exactly
    what has no document.
    """
    from app.services.rag_document import RAGDocumentService

    async with get_worker_db_context() as db:
        row = await RAGDocumentService(db).create_document(
            collection_name=collection_name,
            filename=filename,
            filesize=filesize,
            filetype=Path(filename).suffix.lstrip(".").lower(),
            source_path=source_path,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            ingestion_config=ingestion_config,
            image_description_model=image_description_model,
            embedding_model=embedding_model,
        )
        return str(row.id)


async def _settle_document_row(row_id: str, result: IngestionResult) -> None:
    """Move an open row to what the ingest actually did.

    The failure branch is not an afterthought: a document that failed to parse
    is the one a reader most needs to see, and its reason is a `failure_summary`
    already, built by `ingest_file` rather than by a caller stringifying a
    vendor's exception (#423).
    """
    from app.services.rag_document import RAGDocumentService

    async with get_worker_db_context() as db:
        documents = RAGDocumentService(db)
        if result.status is IngestionStatus.DONE and result.document_id:
            await documents.complete_ingestion(
                row_id,
                vector_document_id=result.document_id,
                chunk_count=result.chunk_count,
                replaced_document_id=result.replaced_document_id,
            )
        else:
            await documents.fail_ingestion(row_id, result.error_message or "Ingestion failed")


async def _run_source_sync(source_id: str, sync_log_id: str | None = None) -> dict[str, Any]:
    """Core sync logic for connector-based sources (shared between all task frameworks).

    Fetches files from a remote connector (e.g. Google Drive, S3), downloads them
    to a temporary directory, and ingests each into the vector store.
    """
    from app.services.rag_sync import RAGSyncService

    async with get_worker_db_context() as db:
        source_svc = SyncSourceService(db)

        source = await source_svc.get_source(source_id)
        connector_cls = CONNECTOR_REGISTRY.get(source.connector_type)
        if not connector_cls:
            await source_svc.update_after_sync(
                source_id, "error", f"Unknown connector: {source.connector_type}"
            )
            return {"status": "error", "message": f"Unknown connector: {source.connector_type}"}

        config = source.config if isinstance(source.config, dict) else json.loads(source.config)
        collection_name = source.collection_name
        sync_mode = source.sync_mode
        organization_id = source.organization_id
        # The credential, unsealed from this organization's vault while there is
        # still a session. It travels beside the config rather than inside it:
        # `config` says how to find the documents and holds nothing that has to
        # be kept (#937). `None` here is a source with no credential, or one
        # whose secret was deleted - the connector refuses rather than reaching
        # for a deployment-wide fallback, because there is not one.
        credential = await _connector_credential(db, source.secret_id, organization_id)

        # Use existing SyncLog (from API trigger) or create new one (from scheduler)
        if sync_log_id:
            log_id = sync_log_id
        else:
            log = await source_svc.trigger_sync(source_id)
            log_id = str(log.id)

        # Before a single file is downloaded: a scheduled sync answers to the
        # same ceiling a run does, and the refusal has to land on the sync log
        # rather than leave it running forever.
        if organization_id is not None:
            try:
                await assert_organization_within_budget(db, organization_id)
            except BudgetExceeded as exc:
                # Through `failure_summary` like every other stored failure,
                # which hands this one back whole: the ceiling and both numbers
                # are ours, they are the organization's own, and they are what
                # the person reading a stopped sync needs (#423).
                reason = failure_summary(exc, stage=IngestionStage.SYNC)
                await RAGSyncService(db).complete_sync(log_id, status="error", error_message=reason)
                await source_svc.update_after_sync(source_id, status="error", error=reason)
                return {"status": "error", "message": reason}

        # One lookup for both answers, in the session that is already open: the
        # collection's parser settings, and the knowledge base id every document
        # this sync creates has to carry. Without the second, a synced document
        # was absent from the knowledge base's Documents tab, from delete and
        # from a collection's own stats, while search over it worked (#992).
        knowledge_base = await _knowledge_base_for(db, collection_name, organization_id)
        ingestion_config = (
            deployment_defaults()
            if knowledge_base is None
            else IngestionConfig.model_validate(knowledge_base.ingestion_config)
        )
        knowledge_base_id = None if knowledge_base is None else knowledge_base.id
        # Both models, resolved once for the collection rather than per file, and
        # recorded on every row this sync writes - the provenance the documents
        # page reads. An upload has carried them since it started tracking; a
        # sync reported neither.
        embedding_model = None if knowledge_base is None else knowledge_base.embedding_model
        image_description_model = await IngestionConfigService(db).resolved_image_model(
            organization_id, ingestion_config
        )
        ingestion_svc = await _ingestion_service_for(
            db, config=ingestion_config, organization_id=organization_id
        )

    connector = connector_cls()

    ingested = updated = skipped = failed = 0
    total = 0
    ledger = SpendLedger(organization_id=organization_id)

    try:
        files = await connector.list_files(config, credential)
        total = len(files)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for remote_file in files:
                try:
                    # `sync_mode` used to reach one argument here and nothing
                    # else, so a scheduled source re-embedded every file every
                    # night - and on the default `new_only` it passed
                    # `replace=False`, which skips the lookup, leaves the old
                    # document in place and inserts a second copy. A week of
                    # nightly syncs was seven copies of every chunk, ranked
                    # against each other in every search (#990). The modes are
                    # `sync_local_flow`'s, deliberately: one column feeds both
                    # flows and they must mean the same thing.
                    existing = StoredDocument()
                    if sync_mode in ("new_only", "update_only"):
                        existing = await ingestion_svc.existing_document(
                            collection_name, remote_file.source_path
                        )
                        # Before the transfer, where the answer allows it:
                        # `update_only` has nothing to do with a file it has
                        # never seen, and downloading one to find that out is a
                        # transfer per new file, every run.
                        if sync_mode == "update_only" and not existing.document_id:
                            skipped += 1
                            continue

                    local_path = await connector.download_file(
                        remote_file, Path(tmp_dir), config=config, credential=credential
                    )

                    # After it, because a hash needs the bytes and no remote
                    # system on this list offers one. A stored document with no
                    # hash is re-ingested rather than assumed current: the
                    # embedding is the cost worth avoiding, and skipping a file
                    # that may have changed is the answer that cannot be
                    # corrected later.
                    if existing.content_hash and (
                        hashlib.sha256(local_path.read_bytes()).hexdigest() == existing.content_hash
                    ):
                        skipped += 1
                        continue

                    # Opened before the ingest, which is the order the upload
                    # path uses and the only one that cannot leave the state this
                    # removes: a row written afterwards and failing - a database
                    # blip, a remote name longer than the column - left the
                    # vector document stored and untracked, and the next
                    # `new_only` run then matched its hash and skipped the file
                    # before reaching the write, for good.
                    row_id = await _open_document_row(
                        filename=remote_file.name,
                        filesize=local_path.stat().st_size,
                        collection_name=collection_name,
                        source_path=remote_file.source_path,
                        organization_id=organization_id,
                        knowledge_base_id=knowledge_base_id,
                        ingestion_config=ingestion_config,
                        image_description_model=image_description_model,
                        embedding_model=embedding_model,
                    )

                    with metered_by(ledger):
                        result = await ingestion_svc.ingest_file(
                            filepath=local_path,
                            collection_name=collection_name,
                            # Unconditional, as in `sync_local_flow`: once this
                            # has decided to ingest, whatever it matched has to
                            # go, or the collection grows a copy.
                            replace=True,
                            source_path=remote_file.source_path,
                        )

                    await _settle_document_row(row_id, result)

                    # On `replaced_document_id`, not on the result's sentence:
                    # `sync_local_flow` reads its own message for the word
                    # "replaced", which is a string it has to keep agreeing with.
                    if result.replaced_document_id:
                        updated += 1
                    else:
                        ingested += 1
                except Exception as e:
                    logger.warning("Failed to sync %s: %s", remote_file.name, e)
                    failed += 1
    except Exception as e:
        logger.error("Source sync failed for %s: %s", source_id, e)
        failed = max(failed, 1)
    finally:
        # The store owns a pooled engine, and this flow runs once per scheduled
        # source, so a store left behind is a pool nothing closes (#948).
        await ingestion_svc.store.aclose()

    await _record_embedding_spend(ledger, organization_id=organization_id, rag_document_id=None)

    async with get_worker_db_context() as db:
        sync_svc = RAGSyncService(db)
        source_svc = SyncSourceService(db)
        try:
            await sync_svc.complete_sync(
                log_id,
                status="done" if not failed else "error",
                total_files=total,
                ingested=ingested,
                updated=updated,
                skipped=skipped,
                failed=failed,
            )
            await source_svc.update_after_sync(
                source_id,
                status="done" if not failed else "error",
                error=f"{failed} files failed" if failed else None,
            )
        except Exception:
            logger.error("Failed to update sync status for source %s", source_id)

    logger.info(
        "Source sync complete: %s - total=%d, ingested=%d, updated=%d, skipped=%d, failed=%d",
        source_id,
        total,
        ingested,
        updated,
        skipped,
        failed,
    )
    return {
        "status": "done" if not failed else "error",
        "total": total,
        "ingested": ingested,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
    }
