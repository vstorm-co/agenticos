"""Services on the deployment's own network, as a client sees them.

No field here carries a credential: a local service is reached without one, which
is what makes it local. `base_url` goes through :data:`ServiceAddress` - the same
rule a sandbox host or a self-hosted Mattermost takes - because the worker POSTs
document pages and query text to whatever is stored here.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.urls import ServiceAddress

LocalServiceKindLiteral = Literal["embedding", "ocr"]


class LocalServiceCreate(BaseSchema):
    """Register a service an organization runs, or the deployment does."""

    name: str = Field(min_length=1, max_length=128, description="What operators call it")
    kind: LocalServiceKindLiteral = Field(
        description=(
            "`embedding` for an OpenAI-compatible embeddings endpoint a collection may "
            "embed through; `ocr` for a LiteParse OCR server a collection's parses may "
            "send pages to."
        )
    )
    provider: str = Field(
        max_length=32,
        description=(
            "For `embedding`, the keyless entry of `GET /rag/embedding-models` that says "
            "which models the service serves (`ollama`); for `ocr`, `liteparse`."
        ),
    )
    base_url: ServiceAddress = Field(
        max_length=512,
        description=(
            "Where it answers - an OpenAI-compatible root such as "
            "`http://ollama:11434/v1`, or the OCR server's root."
        ),
    )
    deployment_wide: bool = Field(
        default=False,
        description=(
            "Owned by the deployment rather than this organization, so every "
            "organization - and an app-scoped collection, which has none - may name "
            "it. Only the deployment's administrator may set this."
        ),
    )


class LocalServiceUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: ServiceAddress | None = Field(default=None, max_length=512)
    is_active: bool | None = None


class LocalServiceRead(BaseSchema, TimestampSchema):
    id: UUID
    organization_id: UUID | None = None
    kind: str
    provider: str
    name: str
    base_url: str
    is_active: bool


class LocalServiceList(BaseSchema):
    items: list[LocalServiceRead]
    total: int
