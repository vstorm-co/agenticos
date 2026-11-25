"""Service connections: the endpoints a collection may be pointed at.

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

from app.api.deps import Auth, ServiceConnectionSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.service_connection import (
    ServiceConnectionCreate,
    ServiceConnectionList,
    ServiceConnectionRead,
    ServiceConnectionUpdate,
)

router = APIRouter()


@router.get(
    "",
    response_model=ServiceConnectionList,
    dependencies=[ASSISTANT, Depends(require(Perm.CONNECTIONS_VIEW))],
)
async def list_service_connections(service: ServiceConnectionSvc, ctx: Auth) -> Any:
    """The organization's own connections and the deployment's."""
    items = await service.list_visible(ctx)
    return ServiceConnectionList(items=items, total=len(items))


@router.post(
    "",
    response_model=ServiceConnectionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[ASSISTANT, Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def create_service_connection(
    data: ServiceConnectionCreate, service: ServiceConnectionSvc, ctx: Auth
) -> Any:
    return await service.create(ctx, data)


@router.patch(
    "/{service_id}",
    response_model=ServiceConnectionRead,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def update_service_connection(
    service_id: UUID, data: ServiceConnectionUpdate, service: ServiceConnectionSvc, ctx: Auth
) -> Any:
    return await service.update(ctx, service_id, data)


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def delete_service_connection(
    service_id: UUID, service: ServiceConnectionSvc, ctx: Auth
) -> None:
    await service.delete(ctx, service_id)
