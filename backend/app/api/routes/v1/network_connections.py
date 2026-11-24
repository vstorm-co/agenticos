"""Explicit, session-bound enrollment of organization-isolated Tailscale nodes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Auth, CurrentSessionId, NetworkConnectionSvc, no_store_response, require
from app.core.permissions import Perm
from app.schemas.network_connection import (
    NetworkConnectionCreate,
    NetworkConnectionList,
    NetworkConnectionRead,
    NetworkEnrollmentRead,
    NetworkPeerList,
)

router = APIRouter(dependencies=[Depends(no_store_response)])


@router.get(
    "", response_model=NetworkConnectionList, dependencies=[Depends(require(Perm.NETWORKS_VIEW))]
)
async def list_connections(
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """List visible connections without starting a node or scanning devices."""
    return await service.list(ctx, session_id=session_id, skip=skip, limit=limit)


@router.post(
    "",
    response_model=NetworkConnectionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.NETWORKS_MANAGE))],
)
async def create_connection(
    data: NetworkConnectionCreate,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Save a record; enrollment requires a separate explicit connect request."""
    return await service.create(ctx, data, session_id=session_id)


@router.get("/{connection_id}", response_model=NetworkConnectionRead)
async def get_connection(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    return await service.get(ctx, connection_id=connection_id, session_id=session_id)


@router.post(
    "/{connection_id}/connect",
    response_model=NetworkConnectionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def connect(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Queue a persistent node's device login, bound to this member and session."""
    return await service.connect(ctx, connection_id=connection_id, session_id=session_id)


@router.get("/{connection_id}/enrollment", response_model=NetworkEnrollmentRead)
async def enrollment(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Return the sensitive login URL only to the session that initiated this attempt."""
    return await service.enrollment(ctx, connection_id=connection_id, session_id=session_id)


@router.get("/{connection_id}/peers", response_model=NetworkPeerList)
async def peers(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Read last observed peer metadata without opening any destination service."""
    return await service.peers(ctx, connection_id=connection_id, session_id=session_id)


@router.post(
    "/{connection_id}/refresh",
    response_model=NetworkConnectionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    return await service.refresh(ctx, connection_id=connection_id, session_id=session_id)


@router.post("/{connection_id}/pause", response_model=NetworkConnectionRead)
async def pause(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Deny new work and fence live leases while retaining the enrolled node identity."""
    return await service.pause(ctx, connection_id=connection_id, session_id=session_id)


@router.post("/{connection_id}/revoke", response_model=NetworkConnectionRead)
async def revoke(
    connection_id: UUID,
    ctx: Auth,
    service: NetworkConnectionSvc,
    session_id: CurrentSessionId,
) -> Any:
    """Deny immediately and queue logout; remote device removal is tracked separately."""
    return await service.revoke(ctx, connection_id=connection_id, session_id=session_id)
