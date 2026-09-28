"""`table.record.upsert`: write the record with an external id, whether or not it exists.

A workflow step is the writer of record for what it upserts, so an update does
not ask for a revision the step never read: when the record exists, the step
reads its current revision from the refusal and writes against it. A record that
changes between that read and the write is a `REVISION_CONFLICT` marked
retryable, and the retry reads again. Nothing is overwritten that the step did
not see.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.schemas.virtual_table import RecordUpsert
from app.services.virtual_tables.exceptions import RevisionRequiredError
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


class TableRecordUpsertConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    table: TableIORef = TABLE_FIELD


class TableRecordUpsertInput(BaseModel):
    """The record's own key and the values to write."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str = Field(min_length=1, max_length=255)
    values: dict[str, Any] = Field(
        default_factory=dict, description="Cell values keyed by column id or label"
    )


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    if not isinstance(config, TableRecordUpsertConfig):
        return []
    return await check_table(db, ctx, config.table, writes=True)


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Create the record, or update it at the revision it is at now."""
    if not isinstance(config, TableRecordUpsertConfig) or not isinstance(
        node_input, TableRecordUpsertInput
    ):
        return not_configured("This step needs a table and a bound external id")

    async def work(service: VirtualTableService, auth: AuthContext) -> NodeResult:
        table = await service.describe_table(auth, config.table.table_id)
        values = column_keyed(table, node_input.values)
        key = operation_key()
        try:
            written = await service.upsert_record(
                auth,
                table.id,
                node_input.external_id,
                RecordUpsert(values=values),
                operation_key=key,
            )
        except RevisionRequiredError as existing:
            written = await service.upsert_record(
                auth,
                table.id,
                node_input.external_id,
                RecordUpsert(values=values, expected_revision=existing.current_revision),
                operation_key=key,
            )
        return Completed[TableRecordOutput](
            output=record_output(table, written.record, created=written.created)
        )

    return await with_service(work)
