"""The organization's AI Architect, as the console's widget and settings read it (#2063).

Console-only: the assistant is how a person in the console gets help, and an
integration that wants to operate the platform calls the public API or `/mcp`.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import AssistantSvc, Auth, require
from app.core.permissions import Perm
from app.schemas.assistant import AssistantRead, AssistantSignals, AssistantUpdate

router = APIRouter()


@router.get("", response_model=AssistantRead)
async def get_assistant(service: AssistantSvc, ctx: Auth) -> Any:
    """The assistant every member of the organization can talk to, installed on first look."""
    return await service.state(ctx)


@router.get("/signals", response_model=AssistantSignals)
async def get_assistant_signals(service: AssistantSvc, ctx: Auth) -> Any:
    """What the widget may raise: approvals waiting, no agents yet, the caller's failed run."""
    return await service.signals(ctx)


@router.patch(
    "",
    response_model=AssistantRead,
    dependencies=[Depends(require(Perm.ORG_SETTINGS))],
)
async def update_assistant(data: AssistantUpdate, service: AssistantSvc, ctx: Auth) -> Any:
    """Change its greeting, or switch it off. Everything else is its agent's, in the Builder."""
    return await service.update(ctx, data)
