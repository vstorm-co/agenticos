"""The organization's AI Architect, as the console's widget and settings read it (#2063).

Console-only: the assistant is how a person in the console gets help, and an
integration that wants to operate the platform calls the public API or `/mcp`.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import AssistantSvc, Auth, require
from app.core.permissions import Perm
from app.schemas.assistant import AssistantRead, AssistantUpdate

router = APIRouter()


@router.get("", response_model=AssistantRead)
async def get_assistant(service: AssistantSvc, ctx: Auth) -> Any:
    """The assistant every member of the organization can talk to, installed on first look."""
    return await service.state(ctx)


@router.patch(
    "",
    response_model=AssistantRead,
    dependencies=[Depends(require(Perm.ORG_SETTINGS))],
)
async def update_assistant(data: AssistantUpdate, service: AssistantSvc, ctx: Auth) -> Any:
    """Rename it, change its greeting, model or company knowledge, or switch it off."""
    return await service.update(ctx, data)
