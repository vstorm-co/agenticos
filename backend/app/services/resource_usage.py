"""Which agents use an organization's skills, context files and knowledge bases.

A thing somebody created and cannot see the use of is a thing they cannot tell
is safe to change or delete, and one they cannot tell they still have to give
to an agent (#2075). The listings of all three ask this once per page.
"""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.repositories import agent_repo
from app.repositories.agent import BoundResourceField
from app.schemas.resource_usage import AgentUsage
from app.services.access import AGENT, accessible_ids


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
    agents = {agent.id: agent for bound in found.values() for agent in bound}
    visible = await accessible_ids(db, ctx, agents.values(), Perm.AGENTS_VIEW, resource_type=AGENT)
    return {
        resource_id: [
            AgentUsage(id=agent.id, name=agent.name) for agent in bound if agent.id in visible
        ]
        for resource_id, bound in found.items()
    }
