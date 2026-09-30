"""`table.create`: make a new table, with a typed schema, as a workflow step.

Administrative, and so its own node: record steps never create tables. It needs
the `tables:create` permission - checked against the graph's author at publish
and the run's principal when it runs. The output names the new table and maps
each column label to its id, so later steps can address the columns without
guessing. A retried step returns the table it already made: the create carries
the step's operation key.

The name is bindable, because a table is unique by name among live tables: a
workflow that runs more than once and makes a table each time binds a name that
differs per run.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.schemas.virtual_table import ColumnInput, TableCreate, VisibilityName
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import not_configured, operation_key, with_service


class TableCreateConfig(BaseModel):
    """The new table: its name, what it is for, its columns, who sees it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=64, json_schema_extra={"x-bindable": True})
    description: str | None = Field(default=None, max_length=500)
    columns: list[ColumnInput] = Field(min_length=1, max_length=100)
    visibility: VisibilityName = "private"


class TableCreatedOutput(BaseModel):
    """The table made, as a reference later steps bind to, and its columns by label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef
    table_id: UUID
    schema_version: int
    columns: dict[str, UUID] = Field(description="Each column's id, keyed by its label")


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if isinstance(config, TableCreateConfig) and not ctx.has(Perm.TABLES_CREATE):
        return [("name", "You cannot create tables")]
    return []


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Create the table, or return the one this step already made."""
    if not isinstance(config, TableCreateConfig):
        return not_configured("This step has no table to create")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.create_table(
            auth,
            TableCreate(
                name=config.name,
                description=config.description,
                columns=config.columns,
                visibility=config.visibility,
            ),
            operation_key=operation_key(),
        )
        return Completed[TableCreatedOutput](
            output=TableCreatedOutput(
                table=TableIORef(table_id=table.id, schema_version=table.schema_version),
                table_id=table.id,
                schema_version=table.schema_version,
                columns={column.label: column.id for column in table.columns},
            )
        )

    return await with_service(work)
