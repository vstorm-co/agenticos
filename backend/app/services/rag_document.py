# ruff: noqa: I001 - Imports structured for Jinja2 template conditionals
"""RAG document service."""

import anyio
import contextlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.rag_document import DocumentStatus, RAGDocument
from app.services.rag.config import get_supported_formats
from app.services.rag.documents import has_indexable_text
from app.services.rag.ingestion import IngestionService
from app.services.rag.vectorstore import BaseVectorStore
from app.repositories import rag_document_repo
from app.schemas.rag import (
    RAGIngestResponse,
    RAGParsedContent,
    RAGParsedPage,
    RAGTrackedDocumentItem,
    RAGTrackedDocumentList,
)
from app.services.file_storage import get_file_storage
from app.services.spend import assert_organization_within_budget
from app.services.ingestion_config import (
    IngestionConfig,
    IngestionConfigService,
    IngestionOverride,
)

logger = logging.getLogger(__name__)


def _tracked_item(doc: RAGDocument) -> RAGTrackedDocumentItem:
    """One tracked document, including what actually read it.

    `parser` is projected out of the stored configuration rather than kept in
    a column of its own, so the headline answer and the full record cannot drift
    apart. A document ingested before any of this was recorded has an empty
    configuration and reports `None`, which is the truth: nobody wrote it down.
    """
    return RAGTrackedDocumentItem(
        id=str(doc.id),
        collection_name=doc.collection_name,
        filename=doc.filename,
        filesize=doc.filesize,
        filetype=doc.filetype,
        status=doc.status,
        error_message=doc.error_message,
        vector_document_id=doc.vector_document_id,
        chunk_count=doc.chunk_count,
        has_file=bool(doc.storage_path),
        created_at=doc.created_at.isoformat() if doc.created_at else None,
        completed_at=doc.completed_at.isoformat() if doc.completed_at else None,
        parser=str(doc.ingestion_config["pdf_parser"]) if doc.ingestion_config else None,
        image_description_model=doc.image_description_model,
        embedding_model=doc.embedding_model,
        was_overridden=doc.ingestion_override is not None,
    )


class RAGDocumentService:
    """Service for RAG document tracking and lifecycle management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_documents(
        self, *, collections: list[str], skip: int = 0, limit: int = 50
    ) -> RAGTrackedDocumentList:
        """List a page of tracked RAG documents belonging to the named collections.

        The `collections` argument is required and takes no default on purpose:
        the caller decides which collections it is entitled to see, and there is
        no way to ask for "all of them" by forgetting to say. An empty list is an
        empty answer.
        """
        rows, total = await rag_document_repo.get_all(
            self.db, collections=collections, skip=skip, limit=limit
        )
        return RAGTrackedDocumentList(
            items=[_tracked_item(d) for d in rows],
            total=total,
        )

    async def list_for_kb(
        self, *, kb_id: UUID, skip: int = 0, limit: int = 50
    ) -> RAGTrackedDocumentList:
        """List documents ingested into a Knowledge Base, paginated."""
        rows, total = await rag_document_repo.get_for_kb(self.db, kb_id, skip=skip, limit=limit)
        return RAGTrackedDocumentList(
            items=[_tracked_item(d) for d in rows],
            total=total,
        )

    async def get_document(self, doc_id: str) -> RAGDocument:
        """Get a RAG document by ID.

        Raises:
            NotFoundError: If document does not exist.
        """
        doc = await rag_document_repo.get_by_id(self.db, UUID(doc_id))
        if not doc:
            raise NotFoundError(
                message="Document not found",
                details={"doc_id": doc_id},
            )
        return doc

    async def create_document(
        self,
        *,
        collection_name: str,
        filename: str,
        filesize: int,
        filetype: str,
        storage_path: str | None = None,
        source_path: str | None = None,
        organization_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
        ingestion_config: IngestionConfig | None = None,
        ingestion_override: IngestionOverride | None = None,
        image_description_model: str | None = None,
        embedding_model: str | None = None,
    ) -> RAGDocument:
        """Create a new RAG document tracking record.

        `source_path` is how the ingest addressed the file, and it is what lets a
        later run find this row again - `discard_failed` retires a previous
        attempt at the *same file* rather than at the same basename, which two
        keys in one bucket share (#996).

        An **upload passes none**, and that is the point of the argument being
        optional. A browser upload's only name is its basename, which is not an
        address: two people can upload different `report.pdf`s and, with
        `replace=false`, mean both to exist. Retiring by that name would delete
        the first one's failed row - its diagnosis, its retry and its stored file
        - for a caller who asked for no such thing.
        """
        if source_path:
            await rag_document_repo.discard_failed(
                self.db, collection_name=collection_name, source_path=source_path
            )
        return await rag_document_repo.create(
            self.db,
            collection_name=collection_name,
            filename=filename,
            filesize=filesize,
            filetype=filetype,
            storage_path=storage_path or "",
            source_path=source_path,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            ingestion_config=(
                None if ingestion_config is None else ingestion_config.model_dump(mode="json")
            ),
            ingestion_override=(
                None
                if ingestion_override is None or ingestion_override.is_empty
                else ingestion_override.model_dump(mode="json", exclude_unset=True)
            ),
            image_description_model=image_description_model,
            embedding_model=embedding_model,
        )

    async def dispatch_upload(
        self,
        *,
        ctx: AuthContext,
        collection: KnowledgeBase,
        file_data: bytes,
        filename: str,
        replace: bool,
        vector_store: Any,
        override: IngestionOverride | None = None,
        organization_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> RAGIngestResponse:
        """Validate, persist, and queue an uploaded file for ingestion.

        Takes the `knowledge_bases` row rather than a collection name, because
        the row is what says how its documents are read. The caller has already
        resolved which collection it may write to; looking the name up again
        here would find whichever row the database returned first, and two
        organizations may share a collection name.

        Performs:
          0. refusal if the organization's monthly budget is already spent -
             ingesting is spending, and the check belongs before the file is
             stored rather than in a worker an hour later;
          1. refusal if the collection's vectors and this deployment's embedding
             model no longer agree - nothing else is worth doing if they do not;
          2. file-extension and size validation, the former against the parser
             *this upload* resolved to rather than the deployment's;
          3. resolution of the image-description model, so a bad profile id in
             an override is refused here and not in a worker an hour later;
          4. permanent storage via `FileStorage`;
          5. a RAGDocument recording the resolved configuration and the override
             that produced it;
          6. lazy creation of the target vector collection;
          7. tmp-copy under `MEDIA_DIR/_rag_tmp` (shared with worker container);
          8. dispatch of the ingestion task on the configured task backend.
        """
        if organization_id is not None:
            await assert_organization_within_budget(self.db, organization_id)

        collection_name = collection.collection_name
        ingestion = IngestionConfigService(self.db)
        ingestion.check_embedding_model(
            collection=collection_name, built_with=collection.embedding_model
        )

        config = IngestionConfig.model_validate(collection.ingestion_config)
        if override is not None:
            config = override.applied_to(config)

        allowed = get_supported_formats(config.pdf_parser.value)
        max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

        ext = Path(filename).suffix.lower()
        if ext not in allowed:
            raise BadRequestError(
                message=f"File type '{ext}' not supported",
                details={"ext": ext, "allowed": sorted(allowed), "parser": config.pdf_parser.value},
            )
        if len(file_data) > max_size:
            raise BadRequestError(
                message=f"File too large. Maximum {settings.MAX_UPLOAD_SIZE_MB}MB.",
                details={"size": len(file_data), "max_mb": settings.MAX_UPLOAD_SIZE_MB},
            )

        image_model = await ingestion.resolved_image_model(ctx.organization_id, config)

        storage = get_file_storage()
        storage_path = await storage.save(f"rag/{collection_name}", filename, file_data)
        rag_doc = await self.create_document(
            collection_name=collection_name,
            filename=filename,
            filesize=len(file_data),
            filetype=ext.lstrip("."),
            storage_path=storage_path,
            organization_id=organization_id,
            knowledge_base_id=knowledge_base_id,
            ingestion_config=config,
            ingestion_override=override,
            image_description_model=image_model,
            embedding_model=collection.embedding_model,
        )
        doc_id = rag_doc.id

        await vector_store.create_collection(collection_name)

        await self._queue_parse(
            doc_id,
            collection_name=collection_name,
            filename=filename,
            file_data=file_data,
            replace=replace,
        )

        return RAGIngestResponse(
            id=str(doc_id),
            status=DocumentStatus.PROCESSING,
            filename=filename,
            collection=collection_name,
            message="File accepted. Processing in background.",
        )

    async def _queue_parse(
        self,
        doc_id: UUID,
        *,
        collection_name: str,
        filename: str,
        file_data: bytes,
        replace: bool,
    ) -> None:
        """Put the file where the worker can read it and dispatch the parse.

        The copy under `MEDIA_DIR/_rag_tmp` is what the flow opens: permanent
        storage may be somewhere the worker container cannot reach, and the
        directory is shared between the two.

        Dispatched with `spawn_after_commit`, not `spawn`. The flow's first act
        is to read this document by id on a session of its own, and until this
        request's transaction commits there is no such row to find (#417).
        """
        tmp_dir = Path(settings.MEDIA_DIR) / "_rag_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = str(tmp_dir / f"{doc_id!s}{Path(filename).suffix.lower()}")
        # anyio, not open(): an upload can be tens of megabytes, and writing it
        # synchronously stalls every other request on this worker until it lands.
        async with await anyio.open_file(tmp_path, "wb") as f:
            await f.write(file_data)
        from app.core.background import spawn_after_commit
        from app.worker.tasks.rag_tasks import ingest_document_flow

        spawn_after_commit(
            self.db,
            ingest_document_flow(
                rag_document_id=str(doc_id),
                collection_name=collection_name,
                filepath=tmp_path,
                source_path=filename,
                replace=replace,
            ),
            name=f"ingest-document-{doc_id}",
        )

    async def complete_ingestion(
        self,
        doc_id: str,
        vector_document_id: str,
        *,
        chunk_count: int,
        replaced_document_id: str | None,
    ) -> None:
        """Mark a document as successfully ingested, retiring what it replaced.

        Neither keyword has a default on purpose. `chunk_count` had one, `0`,
        and all four call sites took it - so every document in the product
        reported an empty collection that answered searches perfectly well
        (#147). `replaced_document_id` is the same shape of trap one step on: a
        call site that omits it leaves a stale row behind and the collection
        over-reports by exactly the size of the document just replaced.
        """
        doc = await self.get_document(doc_id)
        await rag_document_repo.update_status(
            self.db,
            doc.id,
            status=DocumentStatus.DONE,
            vector_document_id=vector_document_id,
            chunk_count=chunk_count,
            completed_at=datetime.now(UTC),
        )
        if replaced_document_id:
            await self._retire_superseded(
                collection_name=doc.collection_name,
                vector_document_id=replaced_document_id,
                keep_id=doc.id,
            )

    async def _retire_superseded(
        self, *, collection_name: str, vector_document_id: str, keep_id: UUID
    ) -> None:
        """Drop the tracking rows for a vector document a replacement deleted.

        Every ingest path creates a fresh `rag_documents` row, including the
        replacing one - the upload, the CLI and the sync all do - while the
        vector store keeps one document. So the old row outlives the vectors it
        describes: `counts_by_collection` sums its `chunk_count` into the
        collection's total, its "view parsed content" reads a document that is
        gone, and a directory synced nightly accumulates one dead row per file
        per run.

        The stored file goes with it, on the same best-effort terms as
        `delete_document`: a storage backend that refuses must not leave the
        database describing vectors nobody holds.
        """
        superseded = await rag_document_repo.get_superseded(
            self.db,
            collection_name=collection_name,
            vector_document_id=vector_document_id,
            keep_id=keep_id,
        )
        for stale in superseded:
            if stale.storage_path:
                try:
                    await get_file_storage().delete(stale.storage_path)
                except Exception as exc:
                    logger.warning("Failed to delete superseded file: %s", exc)
            await rag_document_repo.delete(self.db, stale.id)

    async def fail_ingestion(self, doc_id: str, error_message: str) -> None:
        """Mark a document ingestion as failed."""
        doc = await self.get_document(doc_id)
        await rag_document_repo.update_status(
            self.db,
            doc.id,
            status=DocumentStatus.ERROR,
            error_message=error_message,
            completed_at=datetime.now(UTC),
        )

    async def retry_ingestion(self, doc_id: str) -> RAGDocument:
        """Parse a failed document again, from the file it was uploaded with.

        It reads the stored copy rather than asking for the file again: the
        upload kept one for exactly this, and a retry that needed the original
        would be an upload. `replace=True` because the previous attempt may have
        indexed some of it before failing, and a retry must not leave a document
        represented twice in a collection.

        Dispatching is the whole of the operation. Until #441 this method moved
        the row to `processing`, cleared the error message and dispatched
        nothing - so a retry replaced the diagnosis with a document that would
        stay `processing` for ever, which is worse than the failure it was
        asked to fix.

        Raises:
            NotFoundError: If document does not exist.
            BadRequestError: If the document did not fail, or was ingested
                before uploads kept their file and so has nothing to re-read.
        """
        doc = await self.get_document(doc_id)
        if doc.status != DocumentStatus.ERROR:
            raise BadRequestError(
                message="Only failed documents can be retried",
                details={"doc_id": doc_id, "status": doc.status},
            )
        if not doc.storage_path:
            raise BadRequestError(
                message="This document has no stored file to re-read; upload it again",
                details={"doc_id": doc_id, "filename": doc.filename},
            )
        file_data = await get_file_storage().load(doc.storage_path)
        updated = await rag_document_repo.update_status(
            self.db,
            doc.id,
            status=DocumentStatus.PROCESSING,
            error_message="",
            completed_at=None,
        )
        if updated is None:
            raise NotFoundError(message="Document not found", details={"doc_id": doc_id})
        await self._queue_parse(
            updated.id,
            collection_name=updated.collection_name,
            filename=updated.filename,
            file_data=file_data,
            replace=True,
        )
        return updated

    async def delete_document(
        self,
        doc_id: str,
        ingestion_service: IngestionService,
    ) -> None:
        """Delete a document with cascading cleanup.

        Removes the record from the database and attempts to clean up the vector
        store entry and stored file. Failures in cleanup are logged but do not
        prevent the DB deletion.

        **`ingestion_service` has no default, and that is the whole of it.** It
        was `Any = None`, and the vector cleanup ran only when a caller happened
        to pass one - so `DELETE /kb/{kb_id}/documents/{doc_id}`, which did not,
        removed the row and left the content searchable. A collection then held a
        document nobody could see, delete or re-ingest, because the next
        `new_only` sync matched its unchanged hash and skipped it (#992). That is
        the same trap `complete_ingestion` describes one method down: an argument
        the caller may omit is an argument some caller will.
        """
        doc = await self.get_document(doc_id)

        if doc.vector_document_id:
            try:
                await ingestion_service.remove_document(doc.collection_name, doc.vector_document_id)
            except Exception as e:
                logger.warning("Failed to delete from vector store: %s", e)

        if doc.storage_path:
            try:
                storage = get_file_storage()
                await storage.delete(doc.storage_path)
            except Exception as e:
                logger.warning("Failed to delete file: %s", e)

        await rag_document_repo.delete(self.db, doc.id)

    async def delete_by_collection(self, collection_name: str) -> None:
        """Delete a collection's document rows and unlink their stored uploads.

        The bulk row delete used to return only a count, so nothing removed the
        uploaded files and every one was orphaned on disk when a collection was
        dropped (#1265). The unlink is best-effort - a file already gone is not a
        reason to fail the drop - and mirrors the org purge's teardown.
        """
        storage = get_file_storage()
        for storage_path in await rag_document_repo.delete_by_collection(self.db, collection_name):
            with contextlib.suppress(Exception):
                await storage.delete(storage_path)

    async def get_parsed_content(
        self, doc_id: str, vector_store: BaseVectorStore
    ) -> RAGParsedContent:
        """How a document parsed: its stored chunks, grouped back into pages.

        The chunks in the vector store are the parse - there is no other record
        of what the parser produced - so this reads them back in document order
        rather than re-running a parse that may involve OCR or a paid API.

        `has_text` uses `has_indexable_text`, not `.strip()`: markdown
        reconstruction wraps an unreadable scan in an empty fenced block, which
        is not whitespace and would otherwise pass for content.

        Raises:
            NotFoundError: If the document does not exist, or has not (yet)
                been ingested - a parse that is still running or failed has no
                parsed content to show.
        """
        doc = await self.get_document(doc_id)
        if doc.status != DocumentStatus.DONE or not doc.vector_document_id:
            raise NotFoundError(
                message="No parsed content for this document",
                details={"doc_id": doc_id, "status": doc.status},
            )

        chunks = await vector_store.get_document_chunks(doc.collection_name, doc.vector_document_id)

        pages: list[RAGParsedPage] = []
        for chunk in chunks:
            if not pages or pages[-1].page_num != chunk.page_num:
                pages.append(RAGParsedPage(page_num=chunk.page_num, chunks=[], has_text=False))
            pages[-1].chunks.append(chunk.content)
            if has_indexable_text(chunk.content):
                pages[-1].has_text = True

        return RAGParsedContent(
            id=str(doc.id),
            filename=doc.filename,
            parser=str(doc.ingestion_config["pdf_parser"]) if doc.ingestion_config else None,
            chunk_count=len(chunks),
            has_text=any(page.has_text for page in pages),
            pages=pages,
        )

    async def get_download_info(self, doc_id: str) -> tuple[str, str, str]:
        """Get file download information for a document.

        Returns:
            Tuple of (file_path, filename, mime_type).

        Raises:
            NotFoundError: If document or its file does not exist.
        """
        doc = await self.get_document(doc_id)
        if not doc.storage_path:
            raise NotFoundError(message="No file stored for this document")

        storage = get_file_storage()
        file_path = storage.get_full_path(doc.storage_path)
        if not file_path:
            raise NotFoundError(message="File not found on disk")

        mime_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
            "md": "text/markdown",
        }
        mime_type = mime_map.get(doc.filetype, "application/octet-stream")
        return str(file_path), doc.filename, mime_type
