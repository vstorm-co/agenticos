# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""RAG ingestion & sync tasks — processes documents asynchronously."""

import asyncio
import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from prefect import flow
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_worker_db_context
from app.repositories import knowledge_base_repo
from app.repositories import sync_source as sync_source_repo
from app.services.ingestion_config import (
    IngestionConfig,
    IngestionConfigService,
    deployment_defaults,
)
from app.services.rag.config import DocumentExtensions
from app.services.rag.connectors import CONNECTOR_REGISTRY
from app.services.rag.embeddings import EmbeddingService
from app.services.rag.ingestion import IngestionService
from app.services.rag.models import IngestionStatus
from app.services.sync_source import SyncSourceService
from app.services.rag.vectorstore import PgVectorStore as VectorStore

logger = logging.getLogger(__name__)


async def _ingestion_service_for(
    db: AsyncSession,
    *,
    config: IngestionConfig,
    organization_id: UUID | None,
) -> IngestionService:
    """An ingester that reads documents the way the collection asked to be read.

    The vector store and the embedder are still built from deployment settings:
    the embedding model is fixed per deployment and recorded per collection, and
    the check that the two still agree happens before an upload is accepted.
    What varies here is the parser, the chunker and the image model.
    """
    rag_settings = settings.rag
    embed_service = EmbeddingService(settings=rag_settings)
    vector_store = VectorStore(settings=rag_settings, embedding_service=embed_service)
    processor = await IngestionConfigService(db).build_processor(organization_id, config)
    return IngestionService(processor=processor, vector_store=vector_store)


async def _config_for_collection(
    db: AsyncSession, collection_name: str | None, organization_id: UUID | None
) -> IngestionConfig:
    """The configuration of the knowledge base behind a collection name.

    A sync writes into a collection the same way an upload does, so it has to
    read documents the same way too — a collection set to LiteParse that gets
    PyMuPDF whenever the file arrives from Google Drive is configured in name
    only. The organization narrows the candidates because ``collection_name`` is
    not unique across tenants.

    Falls back to the deployment defaults when no knowledge base claims the
    name. Two cases reach that: a local-directory sync, which names a path on
    the server rather than a collection somebody configured, and a sync source
    with no collection at all — an org-level integration template that exists to
    be cloned and should never have been run.
    """
    if collection_name is None:
        return deployment_defaults()
    for kb in await knowledge_base_repo.list_by_collection_name(db, collection_name):
        if organization_id is None or kb.organization_id == organization_id:
            return IngestionConfig.model_validate(kb.ingestion_config)
    return deployment_defaults()


@flow(name="ingest-document", log_prints=True)
async def ingest_document_flow(
    rag_document_id: str,
    collection_name: str,
    filepath: str,
    source_path: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Process a document: parse, chunk, embed, store in vector DB."""
    logger.info("Starting ingestion: %s -> %s", source_path, collection_name)
    try:
        return await _run_ingestion(
            rag_document_id, collection_name, filepath, source_path, replace
        )
    except Exception as exc:
        logger.error("Ingestion failed: %s", exc)
        await _update_status(rag_document_id, "error", error_message=str(exc))
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
        logger.error("Sync failed: %s", exc)
        await _update_sync_log(sync_log_id, "error", error_message=str(exc))
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

    The configuration comes off the ``rag_documents`` row rather than out of the
    environment, and it is the *resolved* one — the collection's, with whatever
    that upload overrode already folded in. Reading the collection again here
    would quietly re-parse with settings that changed while the file waited in
    the queue, and would lose the override entirely.
    """
    from app.services.rag_document import RAGDocumentService

    async with get_worker_db_context() as db:
        record = await RAGDocumentService(db).get_document(rag_document_id)
        config = IngestionConfig.model_validate(record.ingestion_config)
        ingestion_service = await _ingestion_service_for(
            db, config=config, organization_id=record.organization_id
        )

    file_path = Path(filepath)
    try:
        result = await ingestion_service.ingest_file(
            filepath=file_path,
            collection_name=collection_name,
            replace=replace,
            source_path=source_path,
        )
    except Exception as e:
        await _update_status(rag_document_id, "error", error_message=str(e))
        raise

    # Checked outside the `try` because `ingest_file` *returns* a failure rather
    # than raising one — which is why this used to fall straight through to
    # `complete_ingestion` below. A document whose embeddings were never written
    # was marked `done`, and that is worse than an error: the collection looks
    # ingested, answers nothing, and says nowhere why. Reproduced with no
    # embedding credential configured — the service logged an accurate refusal,
    # the flow finished `Completed()`, the row said `done`, and the vector table
    # held zero rows.
    if result.status is not IngestionStatus.DONE:
        reason = result.error_message or result.message
        await _update_status(rag_document_id, "error", error_message=reason)
        raise RuntimeError(f"Ingestion failed for {source_path}: {reason}")

    try:
        async with get_worker_db_context() as db:
            await RAGDocumentService(db).complete_ingestion(
                rag_document_id, vector_document_id=result.document_id
            )
    except Exception as e:
        await _update_status(rag_document_id, "error", error_message=str(e))
        raise

    logger.info("Ingestion complete: %s", source_path)
    return {"status": "done", "document_id": result.document_id, "filename": source_path}


async def _run_sync(
    sync_log_id: str, source: str, collection_name: str, mode: str, path: str
) -> dict[str, Any]:
    from app.services.rag_document import RAGDocumentService
    from app.services.rag_sync import RAGSyncService

    async with get_worker_db_context() as db:
        ingestion_service = await _ingestion_service_for(
            db,
            config=await _config_for_collection(db, collection_name, None),
            organization_id=None,
        )

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

    for filepath in files:
        async with get_worker_db_context() as db:
            sync_log_check = await RAGSyncService(db).get_sync_log(sync_log_id)
            if sync_log_check.status == "cancelled":
                logger.info("Sync %s cancelled by user", sync_log_id)
                return {
                    "status": "cancelled",
                    "ingested": ingested,
                    "updated": updated,
                    "skipped": skipped,
                    "failed": failed,
                }

        source_path = str(filepath.resolve())
        if mode in ("new_only", "update_only"):
            existing_id = await ingestion_service.find_existing(collection_name, source_path)

            if mode == "new_only":
                if existing_id:
                    # File exists — check if content changed via hash
                    file_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
                    existing_hash = await ingestion_service.get_existing_hash(
                        collection_name, source_path
                    )
                    if existing_hash and file_hash == existing_hash:
                        skipped += 1
                        continue
                    # Hash changed — will re-ingest below

            elif mode == "update_only":
                if not existing_id:
                    skipped += 1
                    continue
                file_hash = hashlib.sha256(filepath.read_bytes()).hexdigest()
                existing_hash = await ingestion_service.get_existing_hash(
                    collection_name, source_path
                )
                if existing_hash and file_hash == existing_hash:
                    skipped += 1
                    continue
        try:
            result = await ingestion_service.ingest_file(
                filepath=filepath, collection_name=collection_name, replace=True
            )
            if result.status.value == "done":
                if result.message and "replaced" in result.message:
                    updated += 1
                else:
                    ingested += 1
                async with get_worker_db_context() as db:
                    doc = await RAGDocumentService(db).create_document(
                        collection_name=collection_name,
                        filename=filepath.name,
                        filesize=filepath.stat().st_size,
                        filetype=filepath.suffix.lstrip(".").lower(),
                    )
                    await RAGDocumentService(db).complete_ingestion(
                        str(doc.id), vector_document_id=result.document_id
                    )
            else:
                failed += 1
        except Exception as e:
            logger.warning("Sync file error %s: %s", filepath.name, e)
            failed += 1

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


async def _update_status(
    rag_document_id: str, status: str, error_message: str | None = None
) -> None:
    from app.services.rag_document import RAGDocumentService

    try:
        async with get_worker_db_context() as db:
            doc_svc = RAGDocumentService(db)
            if status == "error":
                await doc_svc.fail_ingestion(
                    rag_document_id, error_message=error_message or "Unknown error"
                )
            elif status == "done":
                # vector_document_id required for complete_ingestion; callers
                # set status="done" directly in _run_ingestion with the ID.
                pass
    except Exception as e:
        logger.warning("Failed to update RAGDocument status: %s", e)


async def _update_sync_log(sync_log_id: str, status: str, error_message: str | None = None) -> None:
    from app.services.rag_sync import RAGSyncService

    try:
        async with get_worker_db_context() as db:
            await RAGSyncService(db).complete_sync(
                sync_log_id, status=status, error_message=error_message
            )
    except Exception as e:
        logger.warning("Failed to update SyncLog: %s", e)


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

        raw_config = source.config if isinstance(source.config, dict) else json.loads(source.config)
        config = SyncSourceService.decrypt_config_dict(raw_config)
        collection_name = source.collection_name
        sync_mode = source.sync_mode
        organization_id = source.organization_id

        # Use existing SyncLog (from API trigger) or create new one (from scheduler)
        if sync_log_id:
            log_id = sync_log_id
        else:
            log = await source_svc.trigger_sync(source_id)
            log_id = str(log.id)

        ingestion_svc = await _ingestion_service_for(
            db,
            config=await _config_for_collection(db, collection_name, organization_id),
            organization_id=organization_id,
        )

    connector = connector_cls()

    ingested = skipped = failed = total = 0

    try:
        files = await connector.list_files(config)
        total = len(files)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for remote_file in files:
                try:
                    local_path = await connector.download_file(
                        remote_file, Path(tmp_dir), config=config
                    )
                    await ingestion_svc.ingest_file(
                        filepath=local_path,
                        collection_name=collection_name,
                        replace=(sync_mode == "full"),
                        source_path=remote_file.source_path,
                    )
                    ingested += 1
                except Exception as e:
                    logger.warning("Failed to sync %s: %s", remote_file.name, e)
                    failed += 1
    except Exception as e:
        logger.error("Source sync failed for %s: %s", source_id, e)
        failed = max(failed, 1)

    async with get_worker_db_context() as db:
        sync_svc = RAGSyncService(db)
        source_svc = SyncSourceService(db)
        try:
            await sync_svc.complete_sync(
                log_id,
                status="done" if not failed else "error",
                total_files=total,
                ingested=ingested,
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
        "Source sync complete: %s — total=%d, ingested=%d, skipped=%d, failed=%d",
        source_id,
        total,
        ingested,
        skipped,
        failed,
    )
    return {
        "status": "done" if not failed else "error",
        "total": total,
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
    }
