"""Update operations require deployment administration, never an organization role."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import CurrentAppAdmin, UpdateSvc
from app.schemas.updates import (
    AgentUpdateRead,
    UpdateApply,
    UpdateCancel,
    UpdatePrepare,
    UpdateStatusRead,
)

router = APIRouter()


@router.get("", response_model=UpdateStatusRead)
async def status(service: UpdateSvc, _user: CurrentAppAdmin) -> Any:
    """Read the host-owned operation, including after API/container restarts."""
    return await service.status()


@router.post("/prepare", response_model=AgentUpdateRead, status_code=202)
async def prepare(data: UpdatePrepare, service: UpdateSvc, user: CurrentAppAdmin) -> Any:
    """Prepare a published stable version: preflight, immutable images and backup."""
    return await service.prepare(data, actor_user_id=user.id)


@router.post("/apply", response_model=AgentUpdateRead, status_code=202)
async def apply(data: UpdateApply, service: UpdateSvc, user: CurrentAppAdmin) -> Any:
    """Apply a prepared operation now or at its scheduled time; never an arbitrary ref."""
    return await service.apply(data, actor_user_id=user.id)


@router.post("/cancel", response_model=AgentUpdateRead, status_code=202)
async def cancel(data: UpdateCancel, service: UpdateSvc, user: CurrentAppAdmin) -> Any:
    """Cancel only before draining or migration has started."""
    return await service.cancel(data, actor_user_id=user.id)
