"""`table.record.exists`: whether any record of a table matches every filter.

One record is read, not the table: the step leaves by `yes` - carrying that
record's id - or by `no`, so a workflow can skip a lead it already has, or
update it instead of adding a second.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.schemas.virtual_table import RecordFilter, RecordQuery
from app.services.virtual_tables.facade import VirtualTableService
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Completed, NodeResult
from app.workflows.nodes._tables import TABLE_FIELD, check_table, not_configured, with_service


class TableRecordExistsConfig(BaseModel):
    """Which table, and what a record must match."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD
    filters: list[RecordFilter] = Field(default_factory=list, max_length=20)


class TableRecordExistsOutput(BaseModel):
    """Whether a record matches, and the first one's id when one does."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exists: bool
    record_id: UUID | None = None


def routes(output: dict[str, Any] | None) -> frozenset[str]:
    """`yes` or `no`."""
    if output is None:
        return frozenset()
    return frozenset({"yes" if output.get("exists") else "no"})


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """The table, readable by the graph's author and current."""
    if not isinstance(config, TableRecordExistsConfig):
        return []
    return await check_table(db, ctx, config.table, writes=False)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Read the first matching record, if there is one."""
    if not isinstance(config, TableRecordExistsConfig):
        return not_configured("This step has no table")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        page = await service.list_records(
            auth, config.table.table_id, RecordQuery(filters=config.filters, limit=1)
        )
        first = page.items[0] if page.items else None
        return Completed[TableRecordExistsOutput](
            output=TableRecordExistsOutput(
                exists=first is not None, record_id=first.id if first is not None else None
            )
        )

    return await with_service(work)
