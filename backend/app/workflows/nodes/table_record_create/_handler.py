"""`table.record.create`: add a record to the table the step pins.

Values are bound, keyed by column id or by column label; a label is mapped to its
live column. The write carries this step's operation key, so a step redispatched
after a crash replays its first write instead of adding a second record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.schemas.virtual_table import RecordCreate
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


class TableRecordCreateConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class TableRecordCreateInput(BaseModel):
    """The new record's values, and optionally your own key for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: dict[str, Any] = Field(
        default_factory=dict, description="Cell values keyed by column id or label"
    )
    external_id: str | None = Field(default=None, max_length=255)


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordCreateConfig):
        return []
    return await check_table(db, ctx, config.table, writes=True)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Write one new record."""
    if not isinstance(config, TableRecordCreateConfig):
        return not_configured("This step has no table")
    data = (
        node_input if isinstance(node_input, TableRecordCreateInput) else TableRecordCreateInput()
    )

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        written = await service.create_record(
            auth,
            table.id,
            RecordCreate(external_id=data.external_id, values=column_keyed(table, data.values)),
            operation_key=operation_key(),
        )
        return Completed[TableRecordOutput](
            output=record_output(table, written.record, created=True)
        )

    return await with_service(work)
