from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.services.rag.documents import DocumentProcessor
from app.services.rag.failures import IngestionStage, failure_summary
from app.services.rag.models import Document, DocumentInfo, IngestionResult, IngestionStatus
from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)


class _Unset:
    """Sentinel telling an omitted `tenant` argument from an explicit `None`.

    `None` is a real tenant - the deployment-wide rows an app-scoped, personal or
    local collection writes - so a caller that means it must be able to say so and
    not have the ingester's bound tenant stand in (#1684)."""


_UNSET = _Unset()


class _CollectionRemoved(Exception):
    """The collection was deleted while a file was being ingested into it.

    Carried into `_failed` only so the failure names a cause; the document row is
    gone by the time this is raised, so the message is never stored (#1275)."""


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
        tenant: UUID | None = None,
    ):
        self.processor = processor
        self.store = vector_store
        self._on_event = on_event
        # The tenant this ingester's collection belongs to, resolved once from the
        # knowledge base by whoever built this service (the uploading document's
        # base, the sync source's, the flow's) rather than passed per file. It
        # stamps every chunk written and scopes the existing-document lookup and
        # the replace-delete, so one organization cannot find, overwrite or delete
        # another's document in a collection whose name they share (#1684). `None`
        # is a deployment-wide collection - an app-scoped base, the CLI, a
        # local-path sync. Bound rather than per-call because `ingest_file` has
        # many callers and an argument each may omit is one some caller will (the
        # trap #992 was).
        self._tenant = tenant

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
                collection_name,
                source_path=source_path,
                content_hash=content_hash,
                tenant=self._tenant,
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
        *,
        still_wanted: Callable[[], Awaitable[bool]] | None = None,
        source: str | None = None,
        organizational_unit: str | None = None,
        doc_date: str | None = None,
    ) -> IngestionResult:
        """`source_path` accepts URI schemes like gdrive://id or s3://bucket/key.

        Parsing and indexing are caught separately so that the failure this
        returns can say which of the two gave up. It is the one thing the
        caller cannot work out afterwards, and the difference between a file
        this collection's parser does not read and an embedding credential the
        provider refused.

        `still_wanted` is checked after the parse and before the write: parsing a
        large file is slow, and if the collection is dropped while it runs, the
        insert's `CREATE TABLE IF NOT EXISTS` would resurrect the dropped table
        and leave an untracked one behind (#1275). A caller that can tell whether
        the collection still exists passes it so the write is skipped instead.

        The **security-bearing** tenant stamped on every chunk (the conjunct
        retrieval ANDs into every query) is `self._tenant` - resolved once from
        the collection's knowledge base by whoever built this service, never a
        per-call argument. It used to also ride `document.metadata.organization_id`,
        set here from a caller-supplied `organization_id` naming whichever
        organization was *paying* for the embeddings; those agree for an org base,
        but not for an app-scoped one, where `self._tenant` is `None` even though a
        real organization uploaded and paid. Trusting the caller's value left an
        app-scoped base's chunks stamped with whichever organization uploaded
        first - unreachable by both the `IS NULL` scope meant to match them and
        every organization's own equality scope (#1684, FA-039). `document.metadata.organization_id`
        is now mirrored from `self._tenant` alone, so it can only ever agree with
        the value `_build_chunk_metadata` stamps. `source`, `organizational_unit`
        and `doc_date` are the FA-039 business metadata; `document_type` is derived
        here from the parsed filetype (P1). All ride `document.metadata`, so
        `_build_chunk_metadata` writes them per chunk with no change to the write
        path.
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

            # Trusted, security-bearing tenant plus the business dimensions. Set
            # before insert_document so _build_chunk_metadata carries them. Mirrors
            # self._tenant - never a caller-supplied organization_id, which is the
            # paying organization and can disagree with it for an app-scoped base.
            document.metadata.organization_id = (
                str(self._tenant) if self._tenant is not None else None
            )
            document.metadata.source = source
            document.metadata.organizational_unit = organizational_unit
            document.metadata.doc_date = doc_date
            # document_type is the stored filetype/extension, a pure derivation
            # (FA-039 P1). A richer semantic document_category is deferred pending
            # issue-owner confirmation - do not overload document_type with it.
            # Lower-cased so it matches the closed vocabulary (built from the
            # lower-case parser format lists) and the routing that already lowers
            # `suffix.lower()`: `filetype` keeps the original case for display, but
            # a `REPORT.PDF` must be filterable as `pdf`, the only casing a caller
            # can submit past `RetrievalFilters` validation (FA-039 P1).
            filetype = document.metadata.filetype
            document.metadata.document_type = filetype.lower() if filetype else None

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
            if still_wanted is not None and not await still_wanted():
                # The collection was torn down while this file parsed. Its
                # document row went with it, so there is nothing to complete -
                # and writing now would have `_ensure_collection` recreate the
                # dropped table and leave an untracked one holding these vectors
                # (#1275). Abort before the write rather than resurrect it.
                logger.info(
                    "Skipping index for %s: collection %s is gone", filepath.name, collection_name
                )
                return self._failed(
                    _CollectionRemoved(collection_name),
                    stage=IngestionStage.INDEX,
                    filename=filepath.name,
                )

            await self.store.insert_document(
                collection_name=collection_name,
                document=document,
                tenant=self._tenant,
            )

            if existing_id:
                try:
                    await self.store.delete_document(collection_name, existing_id, self._tenant)
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

    async def remove_document(
        self, collection_name: str, document_id: str, tenant: UUID | _Unset | None = _UNSET
    ) -> bool:
        """Wipes all traces of a document from the vector store.

        `tenant` scopes the delete to one tenant's rows on the shared runtime
        table (#1684). A caller that holds the document's own row - the tracking
        service - passes the collection's tenant, exactly the tag the chunks were
        stamped with at ingest; that tenant may be `None` for an app-scoped,
        personal or local document, so it is passed explicitly and the sentinel
        default distinguishes "not given" from a deliberate deployment-wide
        `None`. Omitted, the ingester's own bound tenant stands in.
        """
        scoped = self._tenant if isinstance(tenant, _Unset) else tenant
        try:
            await self.store.delete_document(
                collection_name=collection_name,
                document_id=document_id,
                tenant=scoped,
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
