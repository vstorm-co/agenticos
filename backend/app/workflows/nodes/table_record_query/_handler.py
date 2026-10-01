"""`table.record.query`: one page of a table's records, filtered and sorted.

A page, never the whole table: at most 100 records, with `has_more` saying
whether more match. A workflow that needs to walk more pages asks again with a
later `skip`; silently reading every record of a large table is not something a
step does on its own.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.schemas.virtual_table import RecordFilter, RecordQuery, RecordSort
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.presentation import filters_by_label
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


class TableRecordQueryConfig(BaseModel):
    """Which records, in what order, and how many."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD
    filters: list[RecordFilter] = Field(default_factory=list, max_length=20)
    sort: RecordSort = Field(default_factory=RecordSort)
    limit: int = Field(default=50, ge=1, le=100)
    skip: int = Field(default=0, ge=0, le=10_000, json_schema_extra={"x-bindable": True})


class TableRecordPage(BaseModel):
    """A page of records, and whether more match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[TableRecordOutput, ...]
    has_more: bool


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordQueryConfig):
        return []
    return await check_table(db, ctx, config.table, writes=False)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Read one page."""
    if not isinstance(config, TableRecordQueryConfig):
        return not_configured("This step has no table")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        page = await service.list_records(
            auth,
            table.id,
            RecordQuery(
                filters=filters_by_label(table, config.filters),
                sort=config.sort,
                skip=config.skip,
                limit=config.limit,
            ),
        )
        return Completed[TableRecordPage](
            output=TableRecordPage(
                records=tuple(record_output(table, record) for record in page.items),
                has_more=page.has_more,
            )
        )

    return await with_service(work)
