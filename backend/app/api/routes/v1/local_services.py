"""Services on the deployment's own network that a collection may be pointed at.

Two gates, the ones the vault and the sandbox connections carry. Writing here
decides which host an organization's documents are sent to for embedding or OCR,
so it is `connections:manage`; reading is `connections:view`, because a collection
form has to offer the list to whoever may create a collection. Who may touch a
deployment-wide row - the deployment's administrator alone - is the service's
decision, not a route gate: the same route serves both kinds of row.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, LocalServiceSvc, require
from app.core.permissions import Perm
from app.schemas.local_service import (
    LocalServiceCreate,
    LocalServiceList,
    LocalServiceRead,
    LocalServiceUpdate,
)

router = APIRouter()


@router.get(
    "",
    response_model=LocalServiceList,
    dependencies=[Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def list_local_services(service: LocalServiceSvc, ctx: Auth) -> Any:
    """The organization's own services and the deployment's."""
    items = await service.list_visible(ctx)
    return LocalServiceList(items=items, total=len(items))


@router.post(
    "",
    response_model=LocalServiceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def create_local_service(
    data: LocalServiceCreate, service: LocalServiceSvc, ctx: Auth
) -> Any:
    return await service.create(ctx, data)


@router.patch(
    "/{service_id}",
    response_model=LocalServiceRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def update_local_service(
    service_id: UUID, data: LocalServiceUpdate, service: LocalServiceSvc, ctx: Auth
) -> Any:
    return await service.update(ctx, service_id, data)


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def delete_local_service(service_id: UUID, service: LocalServiceSvc, ctx: Auth) -> None:
    await service.delete(ctx, service_id)
