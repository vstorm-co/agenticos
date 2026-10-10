"""Which agents use an organization's skills, context files and knowledge bases,
and which groups each is shared with.

A thing somebody created and cannot see the use of is a thing they cannot tell
is safe to change or delete, and one they cannot tell they still have to give
to an agent (#2075). Which department it belongs to is the other half of that
card (#2072). The listings ask both once per page.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.repositories import agent_repo, group_repo, resource_grant_repo
from app.repositories.agent import BoundResourceField
from app.schemas.resource_usage import AgentUsage
from app.services.access import AGENT, ResourceType, accessible_ids


async def agents_using(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    field: BoundResourceField,
    resource_ids: Collection[UUID],
) -> dict[UUID, list[AgentUsage]]:
    """For each resource, the agents binding it that the caller may see.

    Narrowed to what `agents:view` reaches, so a skill's card never names a
    private agent its reader could not open. Every requested id is a key.
    """
    found = await agent_repo.binding_resources(
        db, organization_id=ctx.organization_id, field=field, resource_ids=resource_ids
    )
    return await _visible_usage(db, ctx, found)


async def agents_using_mcp(
    db: AsyncSession, ctx: AuthContext, connection_ids: Collection[UUID]
) -> dict[UUID, list[AgentUsage]]:
    """For each organization MCP connection, the agents binding it that the caller may see."""
    found = await agent_repo.binding_mcp_connections(
        db, organization_id=ctx.organization_id, connection_ids=connection_ids
    )
    return await _visible_usage(db, ctx, found)


async def _visible_usage(
    db: AsyncSession, ctx: AuthContext, found: dict[UUID, list[Agent]]
) -> dict[UUID, list[AgentUsage]]:
    agents = {agent.id: agent for bound in found.values() for agent in bound}
    visible = await accessible_ids(db, ctx, agents.values(), Perm.AGENTS_VIEW, resource_type=AGENT)
    return {
        resource_id: [
            AgentUsage(id=agent.id, name=agent.name) for agent in bound if agent.id in visible
        ]
        for resource_id, bound in found.items()
    }


async def groups_sharing(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    resource_type: ResourceType,
    resource_ids: Collection[UUID],
) -> dict[UUID, list[str]]:
    """For each resource, the names of the groups it is shared with, sorted.

    Group names are no secret inside an organization - any member lists them -
    so this needs no narrowing beyond the organization. Every requested id is a
    key, an unshared one with an empty list.
    """
    pairs = await resource_grant_repo.group_grants_for_resources(
        db,
        organization_id=ctx.organization_id,
        resource_type=resource_type.key,
        resource_ids=list(resource_ids),
    )
    names = await group_repo.get_names(
        db, organization_id=ctx.organization_id, group_ids=sorted({group for _, group in pairs})
    )
    shared: dict[UUID, list[str]] = {resource_id: [] for resource_id in resource_ids}
    # Every group a grant names is one of this organization's: the grant's
    # foreign key holds the group, and sharing refuses another tenant's.
    for resource_id, group_id in pairs:
        shared[resource_id].append(names[group_id])
    return {resource_id: sorted(groups) for resource_id, groups in shared.items()}
