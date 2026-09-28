"""What every Virtual Tables node shares: its table, its session, its errors, its key.

Every table node calls `VirtualTableService` - the class the console, the API and
an agent's table tools call - so conflicts, validation, quotas, history, receipts
and audit are the service's and identical on every surface. What lives here is
only what a workflow step needs around it:

- **The table** is pinned in the node's config as a `TableIORef` at publish -
  never a value the running graph computes - and checked then against the graph's
  author (`check_table`). A run's own principal is checked again by the service on
  every call, since a table can be unshared between publishing and running.
- **The key**: a write passes an operation key derived from the attempt's
  idempotency key, the same across retries of this step and distinct in every
  loop iteration, so a redispatched step replays its first write.
- **The errors**: a domain refusal becomes the node's typed failure, field for
  field; a revision conflict is marked retryable, since a fresh read settles it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.db.session import get_worker_db_context
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import RecordRead, TableRead
from app.services.access import TABLE, resolve_access
from app.services.virtual_tables.facade import VirtualTableService
from app.services.virtual_tables.presentation import UnknownColumnError, labelled
from app.services.virtual_tables.receipts import derived_operation_key
from app.services.workflow_execution import context
from app.workflows.contracts.io import TableIORef
from app.workflows.contracts.results import Failed, NodeResult, WorkflowError
from app.workflows.graph.validate import table_ref_problems

TABLE_FIELD = Field(
    json_schema_extra={"x-resource": "table"},
    description="The table this step works on, pinned when the workflow is published.",
)

_RETRYABLE = frozenset({"REVISION_CONFLICT", "CONCURRENT_CHANGE"})


class TableRecordOutput(BaseModel):
    """One record as a step hands it on: by column id for bindings, by label to read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: UUID
    external_id: str | None = None
    revision: int
    values: dict[str, Any] = Field(description="Cell values keyed by column id")
    fields: dict[str, Any] = Field(description="The same values keyed by column label")
    created: bool = False


def record_output(
    table: TableRead, record: RecordRead, *, created: bool = False
) -> TableRecordOutput:
    return TableRecordOutput(
        record_id=record.id,
        external_id=record.external_id,
        revision=record.revision,
        values=dict(record.values),
        fields=labelled(table, record)["values"],
        created=created,
    )


def operation_key() -> str:
    """This step's write key: stable across its retries, distinct per loop iteration."""
    return derived_operation_key("workflow", context.current().idempotency_key)


def refused(exc: AppException) -> Failed:
    """A domain refusal as this node's typed failure."""
    return Failed(
        error=WorkflowError(
            code=exc.code,
            message=exc.message,
            details=exc.details or {},
            retryable=exc.code in _RETRYABLE,
        )
    )


def unknown_column(exc: UnknownColumnError) -> Failed:
    return Failed(error=WorkflowError(code="UNKNOWN_COLUMN", message=str(exc)))


async def with_service(
    work: Callable[[VirtualTableService, AuthContext], Awaitable[NodeResult]],
) -> NodeResult:
    """Run `work` against the table service as the run's principal, in its own session."""
    try:
        async with get_worker_db_context() as db:
            return await work(VirtualTableService(db), context.current().auth)
    except UnknownColumnError as unknown:
        return unknown_column(unknown)
    except AppException as exc:
        return refused(exc)


async def check_table(
    db: AsyncSession, ctx: AuthContext, ref: TableIORef, *, writes: bool
) -> list[tuple[str, str]]:
    """The pinned table, against the graph's author: readable, current, and - for a
    step that writes - editable by them."""
    problems = await table_ref_problems(db, ctx, ref, field="table")
    if problems or not writes:
        return problems
    table = await virtual_table_repo.get_table(
        db, ref.table_id, organization_id=ctx.organization_id
    )
    if table is None or not await resolve_access(
        db, ctx, table, Perm.TABLES_EDIT, resource_type=TABLE
    ):
        return [("table", "You cannot write to this table")]
    return []


def not_configured(what: str) -> Failed:
    return Failed(error=WorkflowError(code="TABLE_STEP_NOT_CONFIGURED", message=what))
