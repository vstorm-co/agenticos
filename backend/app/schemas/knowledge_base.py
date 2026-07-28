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
    # Read-only, and the reason they are exposed at all: a collection whose
    # vectors were produced by a model the deployment no longer uses can no
    # longer be indexed into, and the refusal should not be the first time
    # anybody hears which model that was.
    embedding_model: str
    embedding_dim: int


class KnowledgeBaseList(BaseSchema):
    """Paginated list of Knowledge Bases."""

    items: list[KnowledgeBaseRead]
    total: int
