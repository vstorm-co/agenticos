"""Base class for RAG document source connectors."""

import logging
import tempfile
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from app.services.rag.ingestion import IngestionService
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.db.session import get_db_context
from app.db.vector_tables import VectorWriterKind
from app.services.rag.failures import IngestionStage, failure_summary
from app.services.rag.filters import Source
from app.services.rag_document import RAGDocumentService

logger = logging.getLogger(__name__)


@dataclass
class SourceFile:
    """Metadata about a file available in a source."""

    id: str
    name: str
    mime_type: str = ""
    size: int = 0
    path: str = ""


@dataclass
class SyncResult:
    """Result of a sync operation."""

    total_files: int = 0
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class BaseDocumentSource(ABC):
    """Abstract base for document source connectors.

    Implementations fetch files from external sources (Google Drive, S3, etc.)
    and download them locally for ingestion into the RAG pipeline.
    """

    #: Canonical ingestion origin stamped on every document this source syncs,
    #: so a document brought in through the `rag-sync-*` CLI is filterable by
    #: `source` exactly as one brought in through the worker connector flow is
    #: (FA-039). A subclass that omits it fails fast on the first sync.
    SOURCE: ClassVar[Source]

    @abstractmethod
    async def list_files(
        self, path: str = "", extensions: list[str] | None = None
    ) -> list[SourceFile]:
        """List available files in the source.

        Args:
            path: Path/folder to list (source-specific format).
            extensions: Optional list of extensions to filter by (e.g. [".pdf", ".docx"]).

        Returns:
            List of SourceFile metadata objects.
        """

    @abstractmethod
    async def download_file(self, file_id: str, dest_dir: Path) -> Path:
        """Download a file from the source to a local directory.

        An implementation must put the file where `destination_within` says it
        may go, never at `dest_dir / <a name the source chose>`: a remote name
        is not a path component until something makes it one, and a Drive file
        may legally be called `../../../evil`. Unlike `BaseSyncConnector`, this
        contract cannot hand down a path - it discovers the name mid-download -
        so each implementation calls the helper itself.

        Args:
            file_id: Source-specific file identifier.
            dest_dir: Local directory to download to.

        Returns:
            Path to the downloaded file.
        """

    async def sync(
        self,
        collection_name: str,
        ingestion_service: IngestionService,
        path: str = "",
        extensions: list[str] | None = None,
    ) -> SyncResult:
        """Sync files from source into a RAG collection.

        Lists files, downloads each, and ingests via IngestionService.

        Args:
            collection_name: Target collection name.
            ingestion_service: Service to handle file ingestion.
            path: Source path/folder to sync from.
            extensions: File extensions to include.

        Returns:
            SyncResult with counts of ingested/skipped/failed files.
        """
        result = SyncResult()
        files = await self.list_files(path=path, extensions=extensions)
        result.total_files = len(files)

        with tempfile.TemporaryDirectory(prefix="rag_sync_") as tmp_dir:
            dest = Path(tmp_dir)
            for source_file in files:
                try:
                    local_path = await self.download_file(source_file.id, dest)
                    source_uri = f"{source_file.path or source_file.id}"
                    ingested, error = await self._ingest_tracked(
                        ingestion_service, local_path, collection_name, source_uri
                    )
                    if ingested:
                        result.ingested += 1
                    else:
                        result.failed += 1
                        result.errors.append(f"{source_file.name}: {error}")
                except Exception as e:
                    result.failed += 1
                    result.errors.append(f"{source_file.name}: {e}")
                    logger.error("Failed to sync %s: %s", source_file.name, e)

        return result

    async def _ingest_tracked(
        self, ingestion: IngestionService, local: Path, collection: str, source_path: str
    ) -> tuple[bool, str | None]:
        """Fence an operator sync against teardown and retain each file's outcome."""
        async with get_db_context() as db:
            documents = RAGDocumentService(db)
            await documents.hold_ingestion_name(collection)
            row = await documents.create_document(
                collection_name=collection,
                writer_kind=VectorWriterKind.OPERATOR,
                filename=local.name,
                filesize=local.stat().st_size,
                filetype=local.suffix.lstrip(".").lower(),
                source_path=source_path,
            )
            document_id = row.id
        try:
            result = await ingestion.ingest_file(
                filepath=local,
                collection_name=collection,
                source_path=source_path,
                source=self.SOURCE.value,
                rag_document_id=document_id,
            )
        except Exception as exc:
            async with get_db_context() as db:
                await RAGDocumentService(db).fail_ingestion(
                    str(document_id),
                    error_message=failure_summary(exc, stage=IngestionStage.INGEST),
                    attempt=1,
                )
            raise
        async with get_db_context() as db:
            documents = RAGDocumentService(db)
            if result.status.value != "done":
                error = result.error_message or "The file could not be ingested"
                await documents.fail_ingestion(str(document_id), error_message=error, attempt=1)
                return False, error
            assert result.document_id is not None
            recorded = await documents.complete_ingestion(
                str(document_id),
                vector_document_id=result.document_id,
                chunk_count=result.chunk_count,
                replaced_document_id=result.replaced_document_id,
                attempt=1,
            )
            if not recorded:
                await documents.discard_untracked(
                    collection, result.document_id, scope=ingestion.scope
                )
                return False, "The document was deleted while indexing"
        return True, None
