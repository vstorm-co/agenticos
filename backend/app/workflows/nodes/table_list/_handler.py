"""`table.list`: the tables the run's principal may see, found by name.

The same listing the console's Tables page reads, so a table that is private to
somebody else, or not shared with the principal, is not in it. `search` is part
of a name, bound or typed; archived tables are left out.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.permissions import AuthContext
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import with_service


class TableListConfig(BaseModel):
    """How many tables to list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    limit: int = Field(default=50, ge=1, le=100, description="The most tables to list")


class TableListInput(BaseModel):
    """Part of a table's name, or nothing for every table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    search: str | None = Field(default=None, max_length=200)


class TableSummaryOutput(BaseModel):
    """One table: its id, name and the schema version its columns are at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_id: UUID
    name: str
    description: str | None = None
    schema_version: int


class TableListOutput(BaseModel):
    """The tables found, and how many match in all."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tables: tuple[TableSummaryOutput, ...]
    total: int


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """List the tables the principal may see."""
    limit = config.limit if isinstance(config, TableListConfig) else 50
    search = node_input.search if isinstance(node_input, TableListInput) else None

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        page = await service.list_tables(auth, search=search or None, limit=limit)
        return Completed[TableListOutput](
            output=TableListOutput(
                tables=tuple(
                    TableSummaryOutput(
                        table_id=table.id,
                        name=table.name,
                        description=table.description,
                        schema_version=table.schema_version,
                    )
                    for table in page.items
                ),
                total=page.total,
            )
        )

    return await with_service(work)
