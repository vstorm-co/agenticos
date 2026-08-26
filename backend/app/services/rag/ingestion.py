from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.services.rag.documents import DocumentProcessor
from app.services.rag.failures import IngestionStage, failure_summary
from app.services.rag.models import Document, DocumentInfo, IngestionResult, IngestionStatus
from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredDocument:
    """What a collection already holds for the file being ingested.

    Both fields or neither: they are facts about one document, and returning
    them together is what stops a caller pairing one document's id with
    another's hash (#548). Absent means no match, not an empty document - a
    stored hash of `""` is reported as `None` for the same reason every caller
    gates on truthiness.
    """

    document_id: str | None = None
    content_hash: str | None = None


def _stored(doc: DocumentInfo) -> StoredDocument:
    meta = doc.additional_info or {}
    return StoredDocument(
        document_id=doc.document_id,
        content_hash=meta.get("content_hash") or None,
    )


class IngestionService:
    """File → Parse/Chunk → Deduplicate → Embed/Store → Query-Ready."""

    def __init__(
        self,
        processor: DocumentProcessor,
        vector_store: BaseVectorStore,
        on_event: Callable[..., Awaitable[None]] | None = None,
    ):
        self.processor = processor
        self.store = vector_store
        self._on_event = on_event

    async def _emit(self, event: str, data: dict[str, object]) -> None:
        if self._on_event:
            try:
                await self._on_event(event, data)
            except Exception as e:
                logger.warning("Webhook event dispatch failed: %s", e)

    async def existing_document(
        self, collection_name: str, source_path: str, *, content_hash: str = ""
    ) -> StoredDocument:
        """The stored document this file refers to, id and hash together.

        The precedence and the single-document invariant belong to the store's
        `find_existing_document`: a `source_path` match beats a `filename` one
        beats a `content_hash` one (#548, #990), and the id and hash it returns
        are one document's because they come from one. `PgVectorStore` answers
        it with an indexed lookup per key rather than a full-collection read
        (#1102).

        A store that refuses the lookup answers "no match": a listing this cannot
        read is not evidence the document is absent, but treating it as a match
        would delete a document on the strength of a failed query.
        """
        try:
            doc = await self.store.find_existing_document(
                collection_name, source_path=source_path, content_hash=content_hash
            )
        except Exception as exc:
            logger.warning("Could not check for existing document: %s", exc, exc_info=True)
            return StoredDocument()
        return _stored(doc) if doc is not None else StoredDocument()

    async def ingest_file(
        self,
        filepath: Path,
        collection_name: str,
        replace: bool = True,
        source_path: str = "",
    ) -> IngestionResult:
        """`source_path` accepts URI schemes like gdrive://id or s3://bucket/key.

        Parsing and indexing are caught separately so that the failure this
        returns can say which of the two gave up. It is the one thing the
        caller cannot work out afterwards, and the difference between a file
        this collection's parser does not read and an embedding credential the
        provider refused.
        """
        try:
            document: Document = await self.processor.process_file(filepath)
        except Exception as exc:
            logger.exception("Parsing failed for %s", filepath.name)
            return self._failed(exc, stage=IngestionStage.PARSE, filename=filepath.name)

        try:
            if source_path:
                document.metadata.source_path = source_path
                document.metadata.filename = Path(source_path).name

            existing_id = None
            if replace:
                existing_id = (
                    await self.existing_document(
                        collection_name,
                        document.metadata.source_path or "",
                        content_hash=document.metadata.content_hash or "",
                    )
                ).document_id

            # Inserted before the old one is removed, not after. `insert_document`
            # is where the embeddings are computed, so a provider that refuses
            # between the two statements used to leave the collection with
            # *neither* document - permanently, since the failure is returned
            # rather than raised and nothing retries it. This order fails the
            # other way: a delete that does not happen leaves both, which is
            # visible, searchable and fixable, where neither was none of those
            # (#990).
            await self.store.insert_document(
                collection_name=collection_name,
                document=document,
            )

            if existing_id:
                try:
                    await self.store.delete_document(collection_name, existing_id)
                except Exception:
                    # The ingest *succeeded*: the document asked for is stored.
                    # Failing here used to be reported as a failed ingest, which
                    # made the tracking row say `error` with no vector id while
                    # the vectors existed - and the next attempt at the file then
                    # retired that row as a failure and orphaned them (#996).
                    # What is wrong is that an old document lingers, which is a
                    # duplicate somebody can see and delete.
                    logger.exception(
                        "Stored %s but could not remove the document it replaces (%s)",
                        filepath.name,
                        existing_id,
                    )
                    existing_id = None
                else:
                    logger.info(
                        "Replaced existing document %s for '%s'", existing_id, filepath.name
                    )

            action = "replaced" if existing_id else "ingested"
            chunk_count = len(document.chunked_pages or [])

            await self._emit(
                "rag.document.ingested",
                {
                    "document_id": document.id,
                    "filename": filepath.name,
                    "collection": collection_name,
                    "action": action,
                    "chunks": chunk_count,
                    "source_path": document.metadata.source_path,
                },
            )

            return IngestionResult(
                status=IngestionStatus.DONE,
                document_id=document.id,
                message=f"Successfully {action} '{filepath.name}'",
                chunk_count=chunk_count,
                replaced_document_id=existing_id,
            )

        except Exception as exc:
            logger.exception("Indexing failed for %s", filepath.name)
            return self._failed(exc, stage=IngestionStage.INDEX, filename=filepath.name)

    @staticmethod
    def _failed(exc: Exception, *, stage: IngestionStage, filename: str) -> IngestionResult:
        """The failure a caller may store, for an exception it may not.

        `error_message` reaches `rag_documents` and the documents page, so it
        carries the stage and the exception's type rather than its text - see
        `app.services.rag.failures` for why (#423). The text itself is in the
        `logger.exception` above each call, which also replaced a
        `logger.error(..., e)` that dropped the traceback: that traceback is now
        the only full copy of what the upstream said.
        """
        return IngestionResult(
            status=IngestionStatus.ERROR,
            error_message=failure_summary(exc, stage=stage),
            message=f"Failed to process {filename}",
        )

    async def remove_document(self, collection_name: str, document_id: str) -> bool:
        """Wipes all traces of a document from the vector store."""
        try:
            await self.store.delete_document(
                collection_name=collection_name,
                document_id=document_id,
            )
            await self._emit(
                "rag.document.deleted",
                {
                    "document_id": document_id,
                    "collection": collection_name,
                },
            )
            return True
        except Exception as e:
            logger.error("Failed to delete document %s: %s", document_id, e)
            return False
