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
    embedding_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Whose endpoint serves that model, from "
            "`GET /rag/embedding-models`. Unlike the model this one can be "
            "changed later. Omit for the provider the deployment's own key "
            "belongs to."
        ),
    )
    embedding_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key that pays for this collection's "
            "embeddings. Must be a key for the chosen provider. Omit to use "
            "the deployment's key, which only the deployment's own provider "
            "can be paid with."
        ),
    )
    rerank_model: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Which reranker reorders this collection's search results. Reranking "
            "runs only when this and rerank_secret_id are both set; omit both to "
            "leave it off. Unlike the embedding model this can be changed later."
        ),
    )
    rerank_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key (a Cohere key) that pays for reranking. "
            "Set together with rerank_model."
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
    """Schema for updating a Knowledge Base.

    The embedding *model* is deliberately absent: the vector column was created
    at its width and every stored vector is in its space. The provider and the
    key that pays are here, because the same model served from somewhere else is
    still the same model - which is what makes rotating a credential or moving
    to an organization's own account something other than re-ingesting
    everything.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    ingestion_config: IngestionConfig | None = Field(
        default=None,
        description=(
            "Replaces the collection's configuration wholesale. Takes effect for "
            "documents ingested afterwards; nothing already indexed is re-parsed."
        ),
    )
    # Sent as a pair: both to turn reranking on or change it, both null to turn
    # it off. Whether the caller meant to touch reranking at all is read from
    # the fields they actually sent, so an update that omits both leaves it be.
    rerank_model: str | None = Field(default=None, max_length=128)
    rerank_secret_id: UUID | None = Field(default=None)
    embedding_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Move this collection's embeddings to another provider of the same "
            "model. Refused if that provider does not serve the collection's "
            "model at its recorded width."
        ),
    )
    embedding_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key that pays from now on. Must be a key "
            "for the provider the collection ends up on. Send "
            "`clear_embedding_secret` to go back to the deployment's key."
        ),
    )
    clear_embedding_secret: bool = Field(
        default=False,
        description=(
            "Stop using a vault key and fall back to the deployment's. Needed "
            "because a null `embedding_secret_id` means 'leave it alone' on a "
            "partial update, and both must be sayable."
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
    # Editable, unlike the two above - see `KnowledgeBaseUpdate`.
    embedding_provider: str
    embedding_secret_id: UUID | None = None
    # Both null unless reranking is configured; the secret id is safe to expose,
    # it names a vault row rather than carrying its value.
    rerank_model: str | None = None
    rerank_secret_id: UUID | None = None
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
