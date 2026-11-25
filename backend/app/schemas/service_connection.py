"""Service connections, as a client sees them.

A connection may carry a vault key, and the schemas name it by id only: the key's
value is never a field here, in either direction. `base_url` goes through
:data:`ServiceAddress` - the same rule a sandbox host or a self-hosted Mattermost
takes - because the worker POSTs document pages and query text to whatever is
stored here.
"""

from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import AfterValidator, ConfigDict, Field

from app.schemas.base import BaseSchema, TimestampSchema
from app.schemas.urls import ServiceAddress


def _no_query(value: str) -> str:
    """Refuse a query string or fragment, where a key pasted as `?api-key=` would
    be stored in the clear and echoed back. The key belongs in the vault."""
    parsed = urlparse(value)
    if parsed.query or parsed.fragment:
        raise ValueError(
            "An endpoint address must not carry a query string or fragment - "
            "a key belongs in the vault, chosen on the connection"
        )
    return value


ConnectionAddress = Annotated[ServiceAddress, AfterValidator(_no_query)]

ServiceConnectionKindLiteral = Literal["embedding", "ocr"]


class ServiceConnectionCreate(BaseSchema):
    """Register a service an organization runs, or the deployment does."""

    name: str = Field(min_length=1, max_length=128, description="What operators call it")
    kind: ServiceConnectionKindLiteral = Field(
        description=(
            "`embedding` for an OpenAI-compatible embeddings endpoint a collection may "
            "embed through; `ocr` for a LiteParse OCR server a collection's parses may "
            "send pages to."
        )
    )
    provider: str = Field(
        max_length=32,
        description=(
            "The API style. For `embedding`, an entry of `GET /rag/embedding-models` "
            "reached through a connection: `ollama`, or `openai_compatible` for any "
            "OpenAI-compatible endpoint. For `ocr`, `liteparse`. It cannot be changed "
            "afterwards."
        ),
    )
    base_url: ConnectionAddress = Field(
        max_length=512,
        description=(
            "Where it answers - an OpenAI-compatible root such as "
            "`http://ollama:11434/v1`, or the OCR server's root."
        ),
    )
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "The organization's vault key the endpoint wants, for an `openai_compatible` "
            "connection - a secret whose purpose is `openai_compatible`. Only an "
            "organization's own connection may carry one."
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


class ServiceConnectionUpdate(BaseSchema):
    """Edit a connection. The API style and the kind are fixed at creation, so a
    body naming either is refused rather than ignored."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: ConnectionAddress | None = Field(default=None, max_length=512)
    is_active: bool | None = None
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "Replace the vault key. A keyed connection cannot be set back to no key; "
            "delete it and register another."
        ),
    )


class ServiceConnectionRead(BaseSchema, TimestampSchema):
    id: UUID
    organization_id: UUID | None = None
    kind: str
    provider: str
    name: str
    base_url: str
    is_active: bool
    secret_id: UUID | None = None
    requires_key: bool


class ServiceConnectionList(BaseSchema):
    items: list[ServiceConnectionRead]
    total: int
