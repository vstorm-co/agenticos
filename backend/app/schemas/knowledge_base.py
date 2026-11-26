"""Knowledge Base schemas."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.resource_grant import AudienceChoice
from app.schemas.resource_usage import AgentUsage
from app.services.ingestion_config import IngestionConfig

KBScopeLiteral = Literal["personal", "org", "app"]
VisibilityLiteral = Literal["private", "team", "org"]


class KnowledgeBaseCreate(AudienceChoice):
    """Schema for creating a Knowledge Base."""

    gap_drafter_agent_id: UUID | None = None
    gap_classifier_agent_id: UUID | None = None

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
            "Which embedding model this collection indexes with. The vector column "
            "is created at this model's width, so a later change to the model must "
            "keep that width and is tested first (`PATCH /kb/{id}`). Required for a "
            "new collection."
        ),
    )
    embedding_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Whose endpoint serves that model, from "
            "`GET /rag/embedding-models`. Required for a new collection; a "
            "knowledge base joining a collection name already in use adopts "
            "that collection's."
        ),
    )
    probe_token: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "Required to create a collection on a provider that serves any model "
            "(`openai_compatible`), whose vector width only a test can measure: the "
            "`probe_token` that `POST /kb/embedding-probe` returned for this "
            "connection and model, within ten minutes. The collection is created at "
            "the width the test measured. Not used for any other provider, nor when "
            "joining a collection that already exists."
        ),
    )
    embedding_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key that pays for this collection's "
            "embeddings. Must be a key for the chosen provider. There is no "
            "deployment-wide key: a new personal or organization collection "
            "must name one, and a knowledge base joining an existing collection "
            "adopts its key - a missing one included, which `PATCH /kb/{id}` "
            "then supplies."
        ),
    )
    embedding_base_url: str | None = Field(
        default=None,
        max_length=2048,
        description="OpenRouter embedding API endpoint. Omitted preserves the existing endpoint on update; explicit null restores the global endpoint. Custom endpoints require connections:manage.",
    )
    embedding_endpoint_id: UUID | None = Field(
        default=None,
        description=(
            "Where a provider reached through a connection answers: a service connection of kind "
            "`embedding` whose provider is the chosen one - the organization's own "
            "or the deployment's. Required for a keyless or custom provider, refused "
            "for a keyed one; an app-scoped collection may name only a deployment-wide "
            "service."
        ),
    )
    ingestion_config: IngestionConfig | None = Field(
        default=None,
        description=(
            "How documents put into this collection are parsed, chunked and "
            "described. Omit to inherit this deployment's defaults. The embedding "
            "model is not part of it; it is chosen with `embedding_model`."
        ),
    )


class KnowledgeBaseUpdate(BaseSchema):
    """Schema for updating a Knowledge Base.

    The vector column was created at one width and every stored vector is in one
    space, so a change to where or how the collection embeds - the provider, the
    connection, the key, the endpoint or the model - could strand them. Such a
    change is proven first: `probe_token` from a passing test of exactly these
    settings, or `unverified` to save without one. Renaming, describing or
    reconfiguring ingestion needs neither.
    """

    gap_drafter_agent_id: UUID | None = None
    gap_classifier_agent_id: UUID | None = None

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    ingestion_config: IngestionConfig | None = Field(
        default=None,
        description=(
            "Replaces the collection's configuration wholesale. Takes effect for "
            "documents ingested afterwards; nothing already indexed is re-parsed."
        ),
    )
    embedding_provider: str | None = Field(
        default=None,
        max_length=32,
        description=(
            "Move this collection's embeddings to another provider of the same "
            "model. Refused if that provider does not serve the collection's "
            "model at its recorded width."
        ),
    )
    embedding_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description=(
            "Move the collection to another model, at the width its vectors already "
            "have. Tested like any embedding change: a model of the same width is "
            "still another space unless it answers with the same vectors."
        ),
    )
    embedding_secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization vault key that pays from now on. Must be a key "
            "for the provider the collection ends up on. Null leaves the key "
            "alone; a collection cannot be left without one, because there is "
            "no deployment-wide key to fall back to."
        ),
    )
    embedding_base_url: str | None = Field(
        default=None,
        max_length=2048,
        description="OpenRouter embedding API endpoint. Omitted preserves the existing endpoint on update; explicit null restores the global endpoint. Custom endpoints require connections:manage.",
    )
    embedding_endpoint_id: UUID | None = Field(
        default=None,
        description=(
            "The service connection a keyless or custom provider is reached at from now on. Must "
            "be of kind `embedding` and for the provider the collection ends up "
            "on. Null leaves it alone."
        ),
    )
    probe_token: str | None = Field(
        default=None,
        max_length=2048,
        description=(
            "Proof that a test of exactly these embedding settings passed, from "
            "`POST /kb/{id}/embedding-probe`, within ten minutes. A change to the "
            "provider, connection, key, endpoint or model needs this or `unverified`."
        ),
    )
    unverified: bool = Field(
        default=False,
        description=(
            "Save an embedding change without a passing test. Audited, with the "
            "previous and new settings. Refused when another knowledge base shares the "
            "collection and would be left on different settings."
        ),
    )


class KnowledgeBaseRead(BaseSchema, TimestampSchema):
    """Schema for reading a Knowledge Base (API response)."""

    gap_drafter_agent_id: UUID | None = None
    gap_classifier_agent_id: UUID | None = None

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
    embedding_base_url: str | None = None
    embedding_endpoint_id: UUID | None = None
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
    used_by: list[AgentUsage] = Field(
        default_factory=list,
        description=(
            "The agents whose draft binds this, among those the caller may see - so a "
            "card says where it is used, or that it is used nowhere yet"
        ),
    )
    shared_groups: list[str] = Field(
        default_factory=list,
        description="The groups this is shared with, by name - the departments it belongs to.",
    )


class KnowledgeBaseDetailRead(KnowledgeBaseRead):
    """A single base, with the caller's effective write access."""

    can_edit: bool = Field(description="Whether this caller may write to this knowledge base")


class KnowledgeBaseList(BaseSchema):
    """Paginated list of Knowledge Bases."""

    items: list[KnowledgeBaseRead]
    total: int
