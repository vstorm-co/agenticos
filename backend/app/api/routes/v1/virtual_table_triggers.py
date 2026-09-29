"""A table's triggers - the workflows it runs when a record is added (#1785).

Every route acts on one table, so none carries a `require(...)` gate:
`TableTriggerService` resolves access to that table (and the trigger's
workflow) and reports a refusal as "not found" - see the `permissions-rbac`
skill.

Every write spends the per-member table-write allowance a record write does
(`limit_table_write`, #1823), as a saved view's does.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import Auth, TableTriggerSvc, limit_table_write
from app.schemas.virtual_table import ErrorEnvelope
from app.schemas.virtual_table_trigger import (
    TableTriggerAdmissionList,
    TableTriggerCreate,
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
}
# Not a role gate: the caller may edit the table, but a trigger runs as them, so
# they must also be able to run its workflow's published version.
_CONFIGURE_REFUSALS: dict[int | str, dict[str, Any]] = {
    **_WRITE_REFUSALS,
    400: {"model": ErrorEnvelope, "description": "A filter or a mapping names no live column"},
    403: {"model": ErrorEnvelope, "description": "The caller may not run the workflow"},
    409: {"model": ErrorEnvelope, "description": "The workflow was never published"},
}


@router.get("/{table_id}/triggers", response_model=TableTriggerList, responses=_REFUSALS)
async def list_table_triggers(table_id: UUID, service: TableTriggerSvc, ctx: Auth) -> Any:
    """The workflows this table runs when a record is added."""
    return await service.list_for_table(ctx, table_id)


@router.post(
    "/{table_id}/triggers",
    response_model=TableTriggerRead,
    status_code=status.HTTP_201_CREATED,
    responses=_CONFIGURE_REFUSALS,
    dependencies=[Depends(limit_table_write)],
)
async def create_table_trigger(
    table_id: UUID, data: TableTriggerCreate, service: TableTriggerSvc, ctx: Auth
) -> Any:
    """Run a workflow's live version, as you, for every record added from now on."""
    return await service.create(ctx, table_id, data)


@router.patch(
    "/{table_id}/triggers/{trigger_id}",
    response_model=TableTriggerRead,
    responses=_CONFIGURE_REFUSALS,
    dependencies=[Depends(limit_table_write)],
)
async def update_table_trigger(
    table_id: UUID,
    trigger_id: UUID,
    data: TableTriggerUpdate,
    service: TableTriggerSvc,
    ctx: Auth,
) -> Any:
    """Change a trigger. It runs as you from then on."""
    return await service.update(ctx, table_id, trigger_id, data)


@router.delete(
    "/{table_id}/triggers/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_WRITE_REFUSALS,
    dependencies=[Depends(limit_table_write)],
)
async def delete_table_trigger(
    table_id: UUID, trigger_id: UUID, service: TableTriggerSvc, ctx: Auth
) -> Any:
    """Remove a trigger. Runs it already started keep going."""
    await service.delete(ctx, table_id, trigger_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
