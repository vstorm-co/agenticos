"""Managed app accounts belong to the signed-in person across their workspaces."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import AppConnectionSvc, CurrentUser
from app.schemas.app_connection import (
    AppCatalogRead,
    AppConnectionCallback,
    AppConnectionCreate,
    AppConnectionList,
    AppConnectionRead,
    AppConnectionStartRead,
)

router = APIRouter()


@router.get("/catalog", response_model=AppCatalogRead)
async def app_catalog(
    service: AppConnectionSvc,
    user: CurrentUser,
    search: str = Query(default="", max_length=200),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=24, ge=1, le=100),
) -> Any:
    """Page the official directory; only ready entries can initiate consent."""
    return await service.catalog(search=search, cursor=cursor, limit=limit)


@router.get("", response_model=AppConnectionList)
async def list_app_connections(service: AppConnectionSvc, user: CurrentUser) -> Any:
    return await service.list_for_user(user_id=user.id)


@router.post("/connect", response_model=AppConnectionStartRead, status_code=status.HTTP_201_CREATED)
async def connect_app(
    data: AppConnectionCreate, service: AppConnectionSvc, user: CurrentUser
) -> Any:
    return await service.connect(user_id=user.id, data=data)


@router.post("/callback", response_model=AppConnectionRead)
async def complete_app_connection(
    data: AppConnectionCallback, service: AppConnectionSvc, user: CurrentUser
) -> Any:
    """Authenticate the browser and verify the exact saved grant, never a status query string."""
    return await service.callback(user_id=user.id, data=data)


@router.post("/{connection_id}/refresh", response_model=AppConnectionRead)
async def refresh_app_connection(
    connection_id: UUID, service: AppConnectionSvc, user: CurrentUser
) -> Any:
    return await service.refresh(user_id=user.id, connection_id=connection_id)


@router.post("/{connection_id}/reconnect", response_model=AppConnectionStartRead)
async def reconnect_app(connection_id: UUID, service: AppConnectionSvc, user: CurrentUser) -> Any:
    return await service.reconnect(user_id=user.id, connection_id=connection_id)


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def disconnect_app(connection_id: UUID, service: AppConnectionSvc, user: CurrentUser) -> Any:
    await service.delete(user_id=user.id, connection_id=connection_id)
    return None
