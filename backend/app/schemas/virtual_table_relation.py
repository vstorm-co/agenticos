"""Read-only reverse traversal of one explicitly named relationship."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BacklinkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_table_id: UUID
    column_id: UUID
    skip: int = Field(default=0, ge=0, le=10_000)
    limit: int = Field(default=50, ge=1, le=100)
