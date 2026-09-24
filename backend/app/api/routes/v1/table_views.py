"""Table Views routes: saved filters/sorts/groupings over one table's records.

No route here carries a `require(...)` gate, the same choice `virtual_tables.py`
makes for its own per-table routes: a view is scoped to one table, and access is
resolved against that table (`tables:view` to list, read or delete, `tables:edit`
to create or change one) rather than at the role level, so a Viewer holding an
explicit grant on one table is not refused before the service ever runs. Changing or
deleting a view additionally requires being its owner or holding a `tables:edit`
scope of `ALL`; see `TableViewRead.can_manage`. That refusal is a 404, not a 403:
whether a view exists and who may touch it are not disclosed to a caller who may
not, matching every other per-resource write in this package.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import Auth, TableViewSvc
from app.schemas.table_view import (
    TableViewCreate,
    TableViewList,
    TableViewRead,
    TableViewUpdate,
    ViewKind,
)
from app.schemas.virtual_table import ErrorEnvelope

router = APIRouter()

_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": "No such table or view, or the caller may not manage it",
    },
    409: {"model": ErrorEnvelope, "description": "A view with this name already exists"},
    422: {"model": ErrorEnvelope, "description": "The request does not fit"},
}


@router.get("/{table_id}/views", response_model=TableViewList, responses=_REFUSALS)
async def list_views(
    table_id: UUID,
    service: TableViewSvc,
    ctx: Auth,
    kind: ViewKind | None = Query(None, description="Only views saved for this kind"),
    skip: int = Query(0, ge=0, description="Views to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max views to return"),
) -> Any:
    """The caller's own views plus the shared ones, under this table.

    Their own views come first, then the shared ones, each by name. `total` counts
    every view across all pages.
    """
    return await service.list_views(ctx, table_id, kind=kind, skip=skip, limit=limit)


@router.post(
    "/{table_id}/views",
    response_model=TableViewRead,
    status_code=status.HTTP_201_CREATED,
    responses=_REFUSALS,
)
async def create_view(
    table_id: UUID, data: TableViewCreate, service: TableViewSvc, ctx: Auth
) -> Any:
    """Save a view. Creating one is a table-edit action."""
    return await service.create_view(ctx, table_id, data)


@router.get("/{table_id}/views/{view_id}", response_model=TableViewRead, responses=_REFUSALS)
async def get_view(table_id: UUID, view_id: UUID, service: TableViewSvc, ctx: Auth) -> Any:
    """One view."""
    return await service.get_view(ctx, table_id, view_id)


@router.patch("/{table_id}/views/{view_id}", response_model=TableViewRead, responses=_REFUSALS)
async def update_view(
    table_id: UUID, view_id: UUID, data: TableViewUpdate, service: TableViewSvc, ctx: Auth
) -> Any:
    """Rename, reconfigure or reshare a view.

    Refused (404) to anyone but its owner or a caller whose `tables:edit` scope is `ALL`.
    """
    return await service.update_view(ctx, table_id, view_id, data)


@router.delete(
    "/{table_id}/views/{view_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_REFUSALS,
)
async def delete_view(table_id: UUID, view_id: UUID, service: TableViewSvc, ctx: Auth) -> None:
    """Delete a view. Refused (404) to anyone but its owner or a caller with `tables:edit` `ALL`."""
    await service.delete_view(ctx, table_id, view_id)
