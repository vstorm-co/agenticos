"""A table's triggers - the workflows it runs when a record is added (#1785).

A trigger is made by publishing a workflow whose trigger node is "New table
record"; here it is listed, paused and resumed, and what it decided is read.

Every route acts on one table, so none carries a `require(...)` gate:
`TableTriggerService` resolves access to that table (and the trigger's
workflow) and reports a refusal as "not found" - see the `permissions-rbac`
skill.

Pausing and resuming spend the per-member table-write allowance a record write does
(`limit_table_write`, #1823), as a saved view's write does.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import Auth, TableTriggerSvc, limit_table_write
from app.schemas.virtual_table import ErrorEnvelope
from app.schemas.virtual_table_trigger import (
    TableTriggerAdmissionList,
    TableTriggerList,
    TableTriggerRead,
    TableTriggerUpdate,
)

router = APIRouter()

_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": "No such table, trigger or workflow, or the caller may not reach it",
    },
    422: {"model": ErrorEnvelope, "description": "The request does not fit"},
}
_WRITE_REFUSALS: dict[int | str, dict[str, Any]] = {
    **_REFUSALS,
    429: {
        "model": ErrorEnvelope,
        "description": "Too many table writes in the last minute; see `Retry-After`",
    },
    409: {"model": ErrorEnvelope, "description": "The table is archived"},
}


@router.get("/{table_id}/triggers", response_model=TableTriggerList, responses=_REFUSALS)
async def list_table_triggers(table_id: UUID, service: TableTriggerSvc, ctx: Auth) -> Any:
    """The workflows this table runs when a record is added."""
    return await service.list_for_table(ctx, table_id)


@router.patch(
    "/{table_id}/triggers/{trigger_id}",
    response_model=TableTriggerRead,
    responses=_WRITE_REFUSALS,
    dependencies=[Depends(limit_table_write)],
)
async def update_table_trigger(
    table_id: UUID,
    trigger_id: UUID,
    data: TableTriggerUpdate,
    service: TableTriggerSvc,
    ctx: Auth,
) -> Any:
    """Pause or resume a trigger. It keeps running as whoever published its workflow."""
    return await service.set_active(ctx, table_id, trigger_id, data)


@router.get(
    "/{table_id}/triggers/{trigger_id}/admissions",
    response_model=TableTriggerAdmissionList,
    responses=_REFUSALS,
)
async def list_table_trigger_admissions(
    table_id: UUID,
    trigger_id: UUID,
    service: TableTriggerSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    """What the trigger decided about each added record, newest first - a run, a filter
    miss, a block or a failure, with a reason and never the record's data."""
    return await service.admissions(ctx, table_id, trigger_id, skip=skip, limit=limit)
