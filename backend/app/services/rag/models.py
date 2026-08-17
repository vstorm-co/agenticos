"""RAG Data Models.

Structures used to interface with the RAG feature."""

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field, model_validator


class DocumentImage(BaseModel):
    """An image extracted from a document page."""

    image_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    page_num: int = 0
    image_bytes: bytes = b""
    description: str = ""
    mime_type: str = "image/png"


class DocumentPage(BaseModel):
    """Content of document's page."""

    page_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    page_num: int
    content: str
    parent_doc_id: str | None = None
    images: list[DocumentImage] = Field(default_factory=list)


class DocumentPageChunk(DocumentPage):
    """Content of chunked document's page."""

    chunk_content: str
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    chunk_num: int = 0


class DocumentMetadata(BaseModel):
    """Metadata of a document."""

    filename: str
    filesize: int
    filetype: str
    source_path: str = ""  # original path: local path, s3://bucket/key, gdrive://file_id
    content_hash: str = ""  # SHA256 hash for deduplication
    additional_info: dict[str, Any] | None = None


class Document(BaseModel):
    """A Document object that describes an ingested file."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pages: list[DocumentPage]
    chunked_pages: list[DocumentPageChunk] | None = None
    metadata: DocumentMetadata

    @computed_field  # type: ignore[prop-decorator]
    @property
    def num_pages(self) -> int:
        return len(self.pages)

    @model_validator(mode="after")
    def connect_pages(self) -> "Document":
        for page in self.pages:
            page.parent_doc_id = self.id
        return self


class DocumentChunk(BaseModel):
    """A stored chunk read back from a vector store, as it was indexed."""

    content: str
    page_num: int = 0
    chunk_num: int = 0


class SearchResult(BaseModel):
    """A schema of vector store query output."""

    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_doc_id: str | None = None


class IngestionStatus(StrEnum):
    """A collection of available ingestion statuses."""

    NEW = "new"
    PROCESSING = "processing"
    ADDING = "adding"
    DONE = "done"
    ERROR = "error"


class IngestionResult(BaseModel):
    """A schema to handle document ingestion results.

    `chunk_count` is how many vectors the store now holds for this document. It
    is carried here because the caller records it on the `rag_documents` row and
    has no other way to learn it: it had no field to read, so every call site
    took `complete_ingestion`'s default and every document ever ingested claimed
    zero chunks (#147).

    `replaced_document_id` is the vector document a `replace=True` ingest
    deleted to make room for this one, and is carried for the same reason: the
    tracking row that pointed at it is now stale, and the caller cannot work out
    which row that was. Left unretired, its `chunk_count` keeps being summed
    into the collection's total, so a nightly sync reports a collection growing
    by its own size every night while the vector store holds one copy.
    """

    status: IngestionStatus = IngestionStatus.NEW
    message: str | None = None
    error_message: str | None = None
    document_id: str | None = None
    chunk_count: int = 0
    replaced_document_id: str | None = None


class CollectionInfo(BaseModel):
    """Collection of information about given collection."""

    name: str
    total_vectors: int
    dim: int
    indexing_status: str = "complete"


class DocumentInfo(BaseModel):
    """Information about a document stored in a collection."""

    document_id: str
    filename: str | None = None
    filesize: int | None = None
    filetype: str | None = None
    chunk_count: int = 0
    additional_info: dict[str, Any] | None = None
