"""Which version of an agent answers under which name - the Builder's environments.

Every route here acts on *one* agent, so none of them carries a `require(...)`
gate - the same rule the exposure routes state: a role gate cannot see the
grants on a row, and the decision belongs to the service, which reads the
role scope *and* the grant and reports refusals as "not found".
`tests/api/test_platform_routes.py` enforces both halves.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import AgentEnvironmentSvc, Auth
from app.schemas.agent_environment import (
    EnvironmentCreate,
    EnvironmentList,
    EnvironmentRead,
    EnvironmentUpdate,
)

router = APIRouter()


@router.get("/{agent_id}/environments", response_model=EnvironmentList)
async def list_environments(agent_id: UUID, ctx: Auth, service: AgentEnvironmentSvc) -> Any:
    """Every named environment of this agent, default first."""
    items = await service.list_for_agent(ctx, agent_id)
    return EnvironmentList(items=items, total=len(items))


@router.post(
    "/{agent_id}/environments",
    response_model=EnvironmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    agent_id: UUID, data: EnvironmentCreate, ctx: Auth, service: AgentEnvironmentSvc
) -> Any:
    """Add a named environment, pinned to a version from birth."""
    await service.create(ctx, agent_id, data)
    # Re-read through the listing so the response carries the version number
    # the history names, the same shape the section renders.
    items = await service.list_for_agent(ctx, agent_id)
    return next(item for item in items if item.name == data.name)


@router.patch("/{agent_id}/environments/{environment_id}", response_model=EnvironmentRead)
async def update_environment(
    agent_id: UUID,
    environment_id: UUID,
    data: EnvironmentUpdate,
    ctx: Auth,
    service: AgentEnvironmentSvc,
) -> Any:
    """Repoint (promote) an environment at another version, or rename it."""
    await service.update(ctx, agent_id, environment_id, data)
    items = await service.list_for_agent(ctx, agent_id)
    return next(item for item in items if item.id == environment_id)


@router.delete(
    "/{agent_id}/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_environment(
    agent_id: UUID, environment_id: UUID, ctx: Auth, service: AgentEnvironmentSvc
) -> None:
    """Remove a named environment; exposures on it fall back to the default."""
    await service.delete(ctx, agent_id, environment_id)
