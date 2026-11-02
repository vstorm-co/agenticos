"""The sources a person approved for one read-only watch, retained across publications."""

from uuid import UUID

from pydantic import ConfigDict, Field

from app.schemas.base import BaseSchema


class WatchSources(BaseSchema):
    model_config = ConfigDict(extra="forbid", frozen=True)

    connection_id: UUID
    catalog_key: str
    endpoint_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_tools: tuple[str, ...] | None = None
    collection_ids: tuple[UUID, ...] = ()
    context_ids: tuple[UUID, ...] = ()
    intent_hash: str | None = None
