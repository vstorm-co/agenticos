"""`table.describe`: a table's name and its live columns, for the steps after it.

What the table looks like now - which is what a step that builds a record, a
prompt or a report from it needs to know. Archived columns are left out.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import TABLE_FIELD, check_table, not_configured, with_service


class TableDescribeConfig(BaseModel):
    """Which table."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class ColumnOutput(BaseModel):
    """One live column: its id, label and type, and its options if it picks one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    column_id: UUID
    label: str
    type: str
    nullable: bool
    options: tuple[str, ...] = ()


class TableDescribeOutput(BaseModel):
    """The table and its live columns, in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_id: UUID
    name: str
    description: str | None = None
    schema_version: int
    columns: tuple[ColumnOutput, ...]


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """The table, readable by the graph's author and current."""
    if not isinstance(config, TableDescribeConfig):
        return []
    return await check_table(db, ctx, config.table, writes=False)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Describe the table."""
    if not isinstance(config, TableDescribeConfig):
        return not_configured("This step has no table")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        return Completed[TableDescribeOutput](
            output=TableDescribeOutput(
                table_id=table.id,
                name=table.name,
                description=table.description,
                schema_version=table.schema_version,
                columns=tuple(
                    ColumnOutput(
                        column_id=column.id,
                        label=column.label,
                        type=column.type,
                        nullable=column.nullable,
                        options=tuple(option.label for option in column.options),
                    )
                    for column in table.columns
                    if not column.archived
                ),
            )
        )

    return await with_service(work)
