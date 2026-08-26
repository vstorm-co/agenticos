"""RAG API schemas."""

from typing import Any

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema
from app.services.rag.config import DEFAULT_COLLECTION_NAME


class RAGSearchRequest(BaseSchema):
    """Parameters for a vector search query."""

    collection_name: str = Field(
        DEFAULT_COLLECTION_NAME, description="Target collection for search"
    )
    collection_names: list[str] | None = Field(
        None, description="Search across multiple collections (overrides collection_name)"
    )
    query: str = Field(..., description="Natural language search query")
    limit: int = Field(default=4, ge=1, le=20)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    filter: str | None = Field(
        None, description="Scalar filter expression (e.g. 'filetype == \"pdf\"')"
    )


class RAGSearchResult(BaseSchema):
    """A single retrieved chunk with its associated metadata."""

    content: str
    score: float
    metadata: dict[str, Any]
    parent_doc_id: str


class RAGSearchResponse(BaseSchema):
    """List of results found in the vector store."""

    results: list[RAGSearchResult]


class RAGCollectionInfo(BaseSchema):
    """Statistical information about a specific collection."""

    name: str
    total_vectors: int
    dim: int
    indexing_status: str = "complete"


class RAGCollectionList(BaseSchema):
    """List of all available collection names."""

    items: list[str]


class RAGDocumentItem(BaseSchema):
    """Information about a single document in a collection."""

    document_id: str = Field(..., description="Unique identifier of the document")
    filename: str | None = Field(None, description="Original filename of the document")
    filesize: int | None = Field(None, description="Size of the file in bytes")
    filetype: str | None = Field(None, description="MIME type of the file")
    chunk_count: int = Field(default=0, description="Number of chunks/vectors in the collection")
    additional_info: dict[str, Any] | None = Field(None, description="Additional metadata")


class RAGDocumentList(BaseSchema):
    """List of all documents in a collection."""

    items: list[RAGDocumentItem]
    total: int = Field(..., description="Total number of unique documents")


class RAGMessageResponse(BaseSchema):
    """Simple message response."""

    message: str


class RAGTrackedDocumentItem(BaseSchema):
    """A document tracked in the SQL database."""

    id: str
    collection_name: str
    filename: str
    filesize: int
    filetype: str
    status: str
    error_message: str | None = None
    vector_document_id: str | None = None
    chunk_count: int = 0
    has_file: bool = False
    created_at: str | None = None
    completed_at: str | None = None
    # What actually read this document, rather than what the collection is
    # configured with today. `was_overridden` is stored rather than derived:
    # the collection's configuration moves on, so comparing the two later would
    # start calling ordinary uploads departures.
    parser: str | None = None
    image_description_model: str | None = None
    embedding_model: str | None = None
    was_overridden: bool = False


class RAGTrackedDocumentList(BaseSchema):
    """List of tracked RAG documents."""

    items: list[RAGTrackedDocumentItem]
    total: int


class RAGParsedPage(BaseSchema):
    """One page of a document as the parser left it, chunk by chunk.

    Chunks are returned separately rather than joined because that is what was
    actually indexed - adjacent chunks repeat their configured overlap, and a
    silent join would present the duplication as the parser's mistake.
    """

    page_num: int
    chunks: list[str]
    # Whether anything on this page is worth embedding. Markdown reconstruction
    # wraps an unreadable scan in an empty fenced block, which `.strip()` keeps,
    # so this is `has_indexable_text`, not "the content is non-empty".
    has_text: bool


class RAGParsedContent(BaseSchema):
    """How a document parsed: the stored chunks, reconstructed in page order."""

    id: str
    filename: str
    parser: str | None = None
    chunk_count: int
    has_text: bool
    pages: list[RAGParsedPage]


class RAGIngestResponse(BaseSchema):
    """Response for document ingestion (async or sync)."""

    id: str
    status: str
    filename: str
    collection: str
    message: str
    document_id: str | None = None


class RAGRetryResponse(BaseSchema):
    """Response for document retry."""

    id: str
    status: str
    message: str


class RAGSyncRequest(BaseSchema):
    """Request to trigger a sync operation."""

    collection_name: str = Field(DEFAULT_COLLECTION_NAME, description="Target collection")
    mode: str = Field("full", description="Sync mode: full, new_only, update_only")
    path: str = Field("", description="Source path")


class RAGSyncLogItem(BaseSchema):
    """A sync operation log entry."""

    id: str
    source: str
    collection_name: str
    status: str
    mode: str
    total_files: int = 0
    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    error_message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def serialize_datetime(cls, v: Any) -> str | None:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)


class RAGSyncLogList(BaseSchema):
    """List of sync log entries."""

    items: list[RAGSyncLogItem]
    total: int


class RAGSyncResponse(BaseSchema):
    """Response for sync trigger."""

    id: str
    status: str
    message: str


class SupportedFormatsResponse(BaseSchema):
    parser: str
    formats: list[str]


class EmbeddingModelEntry(BaseSchema):
    model: str
    dim: int


class EmbeddingProviderEntry(BaseSchema):
    """One provider a collection can embed through, and what it serves."""

    provider: str
    name: str
    models: list[EmbeddingModelEntry]
    # Whether this deployment's own key pays here. A collection on any other
    # provider needs a key of its own, and the form says so rather than letting
    # somebody create a collection that cannot index its first document.
    deployment_key: bool


class EmbeddingModelsResponse(BaseSchema):
    """What a collection may be created with, and what an existing one may move to.

    Grouped by provider, because "which models exist" was never the question a
    form needed answered: the list used to be every model this build knew a
    *width* for, which included three sentence-transformer weights and two
    vendors nothing here can call - so the picker offered models whose first
    document would fail to index.
    """

    default: str
    default_provider: str
    providers: list[EmbeddingProviderEntry]
