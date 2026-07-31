"""Knowledge Base schemas."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.services.ingestion_config import IngestionConfig

KBScopeLiteral = Literal["personal", "org", "app"]
VisibilityLiteral = Literal["private", "team", "org"]


class KnowledgeBaseCreate(BaseSchema):
    """Schema for creating a Knowledge Base."""

    name: str = Field(..., min_length=1, max_length=128, description="KB display name")
    description: str | None = Field(default=None, max_length=500)
    scope: KBScopeLiteral = Field(default="personal", description="Visibility scope")
    # Optional - auto-derived from name + a short random suffix when missing.
    collection_name: str | None = Field(
        default=None, min_length=1, max_length=255, description="Vector store collection"
    )
    embedding_model: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Which embedding model this collection indexes with. Frozen at "
            "creation - the vector column is created at this model's width - "
            "so it cannot be changed later. Omit for the deployment default."
        ),
    )
    embedding_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key that pays for this collection's "
            "embeddings. Omit to use the deployment's key."
        ),
    )
    ingestion_config: IngestionConfig | None = Field(
        default=None,
        description=(
            "How documents put into this collection are parsed, chunked and "
            "described. Omit to inherit this deployment's defaults. The embedding "
            "model is deliberately not here: it is recorded from the deployment at "
            "creation and cannot be changed afterwards."
        ),
    )


class KnowledgeBaseUpdate(BaseSchema):
    """Schema for updating a Knowledge Base."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    ingestion_config: IngestionConfig | None = Field(
        default=None,
        description=(
            "Replaces the collection's configuration wholesale. Takes effect for "
            "documents ingested afterwards; nothing already indexed is re-parsed."
        ),
    )


class KnowledgeBaseRead(BaseSchema, TimestampSchema):
    """Schema for reading a Knowledge Base (API response)."""

    id: UUID
    owner_user_id: UUID | None = None
    organization_id: UUID | None = None
    name: str
    description: str | None = None
    scope: KBScopeLiteral
    collection_name: str
    is_default: bool = False
    visibility: VisibilityLiteral = "private"
    ingestion_config: IngestionConfig
    # Read-only after creation: the vector column was created at this model's
    # width, so the choice is frozen with the collection.
    embedding_model: str
    embedding_dim: int
    embedding_secret_id: UUID | None = None
    # Derived per request from `rag_documents`, not stored. Defaulted rather than
    # required so the single-row responses - create, read, update - stay
    # constructible straight from the ORM row, which is what they are: a
    # collection somebody just created holds nothing, and counting to prove it
    # is a query for an answer already known.
    document_count: int = Field(
        default=0,
        description="Tracked documents in this collection, including ones still parsing or failed",
    )
    indexed_count: int = Field(
        default=0,
        description="How many of those finished. Below `document_count` means parsing or failed.",
    )
    chunk_count: int = Field(
        default=0, description="Embedded chunks across this collection's documents"
    )


class KnowledgeBaseList(BaseSchema):
    """Paginated list of Knowledge Bases."""

    items: list[KnowledgeBaseRead]
    total: int
