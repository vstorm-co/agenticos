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

from app.api.deps import Auth, EmbeddingProbeSvc, ServiceConnectionSvc, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.embedding_probe import (
    ConnectionProbeRequest,
    EmbeddingProbeEstimate,
    EmbeddingProbeResult,
)
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


@router.get(
    "/{service_id}/probe/estimate",
    response_model=EmbeddingProbeEstimate,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def estimate_connection_probe(service_id: UUID, service: EmbeddingProbeSvc, ctx: Auth) -> Any:
    """What testing an address or key change would cost: one request per sampled chunk
    of every knowledge base that uses this connection. Sends nothing."""
    return await service.estimate_connection_change(ctx, service_id)


@router.post(
    "/{service_id}/probe",
    response_model=EmbeddingProbeResult,
    dependencies=[Depends(require(Perm.CONNECTIONS_MANAGE))],
)
async def probe_service_connection(
    service_id: UUID, data: ConnectionProbeRequest, service: EmbeddingProbeSvc, ctx: Auth
) -> Any:
    """Test an address or key a connection would move to against every base that uses it.

    A POST, because the address and key id must not sit in a query string. Each base
    is compared in its own scope. A pass returns a `probe_token`, good for ten
    minutes, that `PATCH /service-connections/{id}` takes with the same values; a
    failed test is a 200 with `passed: false`.
    """
    return await service.probe_connection_change(ctx, service_id, data)


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
