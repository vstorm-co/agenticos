"""`table.record.get`: read one record by its id or by its external id.

Not finding it is an answer: the output says `found: false`, so a `logic.if`
can branch on whether a record exists without the run failing on it.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import (
    TABLE_FIELD,
    TableRecordOutput,
    check_table,
    not_configured,
    record_output,
    with_service,
)


class TableRecordGetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class TableRecordGetInput(BaseModel):
    """Exactly one of the record's id or its external id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID | None = None
    external_id: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _exactly_one(self) -> TableRecordGetInput:
        if (self.record_id is None) == (self.external_id is None):
            raise ValueError("Bind exactly one of record_id or external_id")
        return self


class TableRecordLookup(BaseModel):
    """Whether the record exists, and it when it does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    found: bool
    record: TableRecordOutput | None = None


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordGetConfig):
        return []
    return await check_table(db, ctx, config.table, writes=False)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Look the record up."""
    if not isinstance(config, TableRecordGetConfig) or not isinstance(
        node_input, TableRecordGetInput
    ):
        return not_configured("This step needs a table and a bound record id or external id")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        try:
            record = (
                await service.get_record(auth, table.id, node_input.record_id)
                if node_input.record_id is not None
                else await service.get_record_by_external_id(
                    auth, table.id, str(node_input.external_id)
                )
            )
        except NotFoundError:
            return Completed[TableRecordLookup](output=TableRecordLookup(found=False))
        return Completed[TableRecordLookup](
            output=TableRecordLookup(found=True, record=record_output(table, record))
        )

    return await with_service(work)
