"""System agents: the platform's own background roles, their model, budget and history (#2575).

One gate, `budgets:manage`, for reading and writing alike: a role's model and
budget are spending decisions, and its history carries cost. The daily briefing is
listed but read-only here - it is the organization's proactivity setting.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import Auth, SystemAgentSvc, require
from app.core.permissions import Perm
from app.schemas.system_agent import SystemAgentList, SystemAgentRead, SystemAgentUpdate

router = APIRouter()


@router.get(
    "",
    response_model=SystemAgentList,
    dependencies=[Depends(require(Perm.BUDGETS_MANAGE))],
)
async def list_system_agents(service: SystemAgentSvc, ctx: Auth) -> Any:
    """Each role's switch, model, monthly budget, this month's spend and recent executions."""
    return await service.overview(ctx)


@router.put(
    "/{role}",
    response_model=SystemAgentRead,
    dependencies=[Depends(require(Perm.BUDGETS_MANAGE))],
)
async def update_system_agent(
    role: str, data: SystemAgentUpdate, service: SystemAgentSvc, ctx: Auth
) -> Any:
    """Replace memory maintenance's switch, model and budget."""
    return await service.update(ctx, role, data)
