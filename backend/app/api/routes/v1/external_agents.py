"""Remote A2A agents an organization's agents may delegate to (#2092)."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import Auth, ExternalAgentSvc, require
from app.api.public_api import PUBLIC
from app.core.permissions import Perm
from app.schemas.external_agent import ExternalAgentCreate, ExternalAgentList, ExternalAgentRead

# Public: an integration that runs agents over the API may also register the
# remote agents they delegate to, under the same permissions.
router = APIRouter(dependencies=[PUBLIC])


@router.get(
    "",
    response_model=ExternalAgentList,
    dependencies=[Depends(require(Perm.AGENTS_VIEW))],
)
async def list_external_agents(service: ExternalAgentSvc, ctx: Auth) -> Any:
    """Every remote agent registered in this organization."""
    return await service.list(ctx)


@router.post(
    "",
    response_model=ExternalAgentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def register_external_agent(
    data: ExternalAgentCreate, service: ExternalAgentSvc, ctx: Auth
) -> Any:
    """Register a remote agent by its A2A agent card, read and checked now."""
    return await service.register(ctx, data)


@router.post(
    "/{external_agent_id}/refresh",
    response_model=ExternalAgentRead,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def refresh_external_agent(
    external_agent_id: UUID, service: ExternalAgentSvc, ctx: Auth
) -> Any:
    """Read the remote agent's card again."""
    return await service.refresh(ctx, external_agent_id)


@router.delete(
    "/{external_agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require(Perm.AGENTS_EDIT))],
)
async def delete_external_agent(
    external_agent_id: UUID, service: ExternalAgentSvc, ctx: Auth
) -> None:
    """Remove a registration."""
    await service.delete(ctx, external_agent_id)
