"""`table.record.update`: change some of one record's cells.

`expected_revision` is optional here, unlike on the API: a step that read the
record earlier binds the revision it read, and a conflict then means someone
else changed it in between. A step that has no revision to send writes against
the record's current one, read under the record's lock - and a retry after that
write committed replays it rather than being refused as a different request.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.schemas.virtual_table import RecordUpdate
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.presentation import column_keyed
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import (
    TABLE_FIELD,
    TableRecordOutput,
    check_table,
    not_configured,
    operation_key,
    record_output,
    with_service,
)


class TableRecordUpdateConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class TableRecordUpdateInput(BaseModel):
    """Which record, the cells to change, and the revision it was read at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    values: dict[str, Any] = Field(description="Only the cells to change, by column id or label")
    expected_revision: int | None = Field(default=None, ge=1)


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordUpdateConfig):
        return []
    return await check_table(db, ctx, config.table, writes=True)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Change the bound cells of the bound record."""
    if not isinstance(config, TableRecordUpdateConfig) or not isinstance(
        node_input, TableRecordUpdateInput
    ):
        return not_configured("This step needs a table and a bound record id")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        values = column_keyed(table, node_input.values)
        if node_input.expected_revision is None:
            written = await service.update_record_cells(
                auth, table.id, node_input.record_id, values, operation_key=operation_key()
            )
        else:
            written = await service.update_record(
                auth,
                table.id,
                node_input.record_id,
                RecordUpdate(expected_revision=node_input.expected_revision, values=values),
                operation_key=operation_key(),
            )
        return Completed[TableRecordOutput](output=record_output(table, written.record))

    return await with_service(work)
