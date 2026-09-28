"""`table.record.delete`: delete one record. Its history stays."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import (
    TABLE_FIELD,
    check_table,
    not_configured,
    operation_key,
    with_service,
)


class TableRecordDeleteConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class TableRecordDeleteInput(BaseModel):
    """Which record, and the revision it was read at, if the step read it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    expected_revision: int | None = Field(default=None, ge=1)


class TableRecordDeleteOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordDeleteConfig):
        return []
    return await check_table(db, ctx, config.table, writes=True)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Delete the bound record."""
    if not isinstance(config, TableRecordDeleteConfig) or not isinstance(
        node_input, TableRecordDeleteInput
    ):
        return not_configured("This step needs a table and a bound record id")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        revision = node_input.expected_revision
        if revision is None:
            revision = (
                await service.get_record(auth, config.table.table_id, node_input.record_id)
            ).revision
        await service.delete_record(
            auth,
            config.table.table_id,
            node_input.record_id,
            expected_revision=revision,
            operation_key=operation_key(),
        )
        return Completed[TableRecordDeleteOutput](
            output=TableRecordDeleteOutput(record_id=node_input.record_id)
        )

    return await with_service(work)
