"""Which agents use an organization's skills, context files and knowledge bases,
and which groups each is shared with.

A thing somebody created and cannot see the use of is a thing they cannot tell
is safe to change or delete, and one they cannot tell they still have to give
to an agent (#2075). Which department it belongs to is the other half of that
card (#2072). The listings ask both once per page.
"""

import json
from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus
from app.repositories import agent_environment_repo, agent_repo, group_repo, resource_grant_repo
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
            AgentUsage(
                id=agent.id,
                name=agent.name,
                slug=agent.slug,
                has_avatar=agent.has_avatar,
                avatar_color=agent.avatar_color,
            )
            for agent in bound
            if agent.id in visible
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

    Group names are the member directory - any member lists them, a key only
    when issued `members:view` - so a caller without it is told of no group.
    Every requested id is a key, an unshared one with an empty list.
    """
    if not ctx.has(Perm.MEMBERS_VIEW):
        return {resource_id: [] for resource_id in resource_ids}
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


async def shared_with_group(
    db: AsyncSession, ctx: AuthContext, *, resource_type: ResourceType, group_id: UUID | None
) -> list[UUID] | None:
    """The resources of one type shared with a group, or None for no narrowing.

    How a listing is grouped by department (#2124): a group is already who a
    resource reaches, so grouping by one is a filter on its grants rather than
    a second hierarchy beside them. The listing still applies its own
    visibility rules on top, so a group's resource the caller cannot open is
    never listed. A group from another organization names no grants here.
    """
    if group_id is None:
        return None
    return await resource_grant_repo.ids_shared_with_group(
        db, organization_id=ctx.organization_id, resource_type=resource_type.key, group_id=group_id
    )


def in_use_by(named: Sequence[Agent], hidden: int) -> str:
    """Who uses something, for a refusal: the agents the caller may see by name, and a
    count of the rest."""
    names = ", ".join(f"'{agent.name}'" for agent in named)
    if not named:
        return f"{hidden} agent{'' if hidden == 1 else 's'} you cannot see"
    return f"{names} and {hidden} more you cannot see" if hidden else names


def _binds_skill(spec: dict[str, Any], skill_id: UUID) -> bool:
    """Whether a stored spec that names the skill's id binds it, itself or through an
    inline specialist.

    Callers pass only the specs the database found naming the id. One that no longer
    parses is taken to bind it: the skill is not deleted from under a draft its owner
    has yet to fix.
    """
    from app.services.eval_suite import binds

    try:
        return binds(AgentSpec.model_validate(spec), "skill", skill_id)
    except ValidationError:
        return True


async def agents_using_skill(
    db: AsyncSession, *, organization_id: UUID, skill_id: UUID
) -> list[Agent]:
    """The live agents a skill cannot be deleted from under, in name order.

    Those whose draft binds it, or a version one of their environments serves -
    the agent itself or an inline specialist it defines. Archived agents use
    nothing; nobody runs them.
    """
    using: set[UUID] = set()
    for environment, version in await agent_environment_repo.served_mentioning(
        db, [str(skill_id)], organization_id=organization_id
    ):
        if environment.agent_id not in using and _binds_skill(version.spec, skill_id):
            using.add(environment.agent_id)
    for agent in await agent_repo.drafts_mentioning(
        db, str(skill_id), organization_id=organization_id
    ):
        if agent.id not in using and _binds_skill(agent.draft_spec, skill_id):
            using.add(agent.id)
    agents = await agent_repo.get_many(db, sorted(using), organization_id=organization_id)
    return sorted(
        (agent for agent in agents.values() if agent.status != AgentStatus.ARCHIVED.value),
        key=lambda agent: agent.name,
    )


async def agents_serving_skills(
    db: AsyncSession, ctx: AuthContext, *, skill_ids: Collection[UUID]
) -> dict[UUID, list[AgentUsage]]:
    """For each skill, the agents a served version of which binds it, that the caller may see.

    A skill's agents are the ones that run it: a version one of their environments
    serves binds it, the agent's own or an inline specialist's. A draft that binds
    it runs nothing yet.
    """
    from app.services.eval_suite import binds

    serving: dict[UUID, set[UUID]] = {skill_id: set() for skill_id in skill_ids}
    for environment, version in await agent_environment_repo.served_mentioning(
        db, [str(skill_id) for skill_id in skill_ids], organization_id=ctx.organization_id
    ):
        text = json.dumps(version.spec)
        named = [skill_id for skill_id in skill_ids if str(skill_id) in text]
        try:
            spec = AgentSpec.model_validate(version.spec)
        except ValidationError:
            continue
        for skill_id in named:
            if binds(spec, "skill", skill_id):
                serving[skill_id].add(environment.agent_id)
    agents = await agent_repo.get_many(
        db,
        sorted({agent_id for ids in serving.values() for agent_id in ids}),
        organization_id=ctx.organization_id,
    )
    found = {
        skill_id: sorted(
            (
                agents[agent_id]
                for agent_id in ids
                if agent_id in agents and agents[agent_id].status != AgentStatus.ARCHIVED.value
            ),
            key=lambda agent: agent.name,
        )
        for skill_id, ids in serving.items()
    }
    return await _visible_usage(db, ctx, found)
