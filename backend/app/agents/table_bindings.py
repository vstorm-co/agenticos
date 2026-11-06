"""Table grants used by published app bindings, independent of agent tools."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TABLE_GRANTS_RESOURCE = "table_grants"


class TableOperation(StrEnum):
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class TableGrant(BaseModel):
    """Operations an app published by an agent may bind to one table."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    table_id: UUID
    operations: tuple[TableOperation, ...] = Field(default=(TableOperation.READ,), min_length=1)
