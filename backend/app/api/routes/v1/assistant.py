"""The organization's AI Architect, as the console's widget and settings read it (#2063).

The legacy widget read installs defaults. MCP uses the side-effect-free
configuration read and explicit installation instead.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import AssistantSvc, Auth, require
from app.api.public_api import ASSISTANT
from app.core.permissions import Perm
from app.schemas.assistant import (
    AssistantConfigurationRead,
    AssistantRead,
    AssistantSignals,
    AssistantUpdate,
)

router = APIRouter()


@router.get("", response_model=AssistantRead)
async def get_assistant(service: AssistantSvc, ctx: Auth) -> Any:
    """The assistant every member of the organization can talk to, installed on first look."""
    return await service.state(ctx)


@router.get(
    "/configuration",
    response_model=AssistantConfigurationRead,
    dependencies=[ASSISTANT, Depends(require(Perm.ORG_SETTINGS))],
)
async def read_assistant_configuration(service: AssistantSvc, ctx: Auth) -> Any:
    """Read current configuration without installing or publishing agents."""
    return await service.configuration(ctx)


@router.post(
    "/install",
    response_model=AssistantRead,
    dependencies=[ASSISTANT, Depends(require(Perm.ORG_SETTINGS))],
)
async def install_assistant(service: AssistantSvc, ctx: Auth) -> Any:
    """Explicitly install/refresh shipped assistants; ready defaults may be published."""
    return await service.state(ctx)


@router.get("/signals", response_model=AssistantSignals)
async def get_assistant_signals(service: AssistantSvc, ctx: Auth) -> Any:
    """What the widget may raise: approvals waiting, no agents yet, the caller's failed run."""
    return await service.signals(ctx)


@router.patch(
    "",
    response_model=AssistantRead,
    dependencies=[ASSISTANT, Depends(require(Perm.ORG_SETTINGS))],
)
async def update_assistant(data: AssistantUpdate, service: AssistantSvc, ctx: Auth) -> Any:
    """Change its greeting, or switch it off. Everything else is its agent's, in the Builder."""
    return await service.update(ctx, data)
