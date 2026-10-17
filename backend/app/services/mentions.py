"""`@`-mentions: what a person may point an agent at, and what reaches the model (#2189).

A mention never widens what an agent may reach. What the composer offers is what
the chat's agent already has - its MCP servers, its knowledge bases, skills and
context files, its delegates - plus the other agents the person may run. A frame
is resolved against that same list on the server, so an id the person could not
have picked is dropped rather than trusted, and the run still checks every access
it would have checked without the mention.

What reaches the model is a short note naming each thing and how to use it, never
the thing's content.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import PLATFORM_MCP_PREFIX, tool_prefix
from app.agents.spec import (
    AgentSpec,
    OrgMcpServerRef,
    PersonalMcpServerRef,
)
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.repositories import agent as agent_repo
from app.repositories import context as context_repo
from app.repositories import knowledge_base as knowledge_base_repo
from app.repositories import mcp_connection as mcp_connection_repo
from app.repositories import skill as skill_repo
from app.schemas.mention import Mentionable, MentionRef
from app.services.access import AGENT, accessible_ids, visible_resource_ids
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_catalog import get_entry

_AGENTS_OFFERED = 50
"""How many other agents the menu lists. Typing narrows it on the client."""


@dataclass(frozen=True)
class ResolvedMentions:
    """A frame's mentions, checked: what the turn runs on and what the model is told."""

    agent_id: UUID
    """The agent the turn runs on - the chat's own, or one mentioned that it cannot delegate to."""

    mentions: list[Mentionable]
    """What the transcript shows as chips, in the order they were picked."""

    note: str | None
    """Appended to the person's message for the model; `None` when nothing was mentioned."""


def _bound(spec: AgentSpec, capability_id: str) -> bool:
    return any(binding.id == capability_id and binding.enabled for binding in spec.capabilities)


class MentionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def available(self, ctx: AuthContext, agent_id: UUID) -> list[Mentionable]:
        """Everything the person may point this agent at, servers first.

        Raises:
            NotFoundError, AuthorizationError: If the caller may not run the agent.
        """
        _agent, spec, _version = await AgentRegistryService(self.db).get_runnable_spec(
            ctx, agent_id
        )
        return [
            *await self._servers(ctx, spec),
            *await self._agents(ctx, agent_id, spec),
            *await self._knowledge(ctx, spec),
        ]

    async def resolve(
        self, ctx: AuthContext, agent_id: UUID, refs: list[MentionRef]
    ) -> ResolvedMentions:
        """A frame's mentions against what the person could have picked.

        An agent the chat's agent does not delegate to is where the turn runs: the
        person named who should answer. The rest is resolved against *that*
        agent, because they are its servers and knowledge the turn will reach.
        """
        if not refs:
            return ResolvedMentions(agent_id=agent_id, mentions=[], note=None)
        offered = {(item.kind, item.id): item for item in await self.available(ctx, agent_id)}
        runs_on = next(
            (
                offered[(ref.kind, ref.id)]
                for ref in refs
                if ref.kind == "agent"
                and (ref.kind, ref.id) in offered
                and not offered[(ref.kind, ref.id)].delegate
            ),
            None,
        )
        if runs_on is not None:
            agent_id = UUID(runs_on.id)
            offered = {(item.kind, item.id): item for item in await self.available(ctx, agent_id)}
        picked: list[Mentionable] = [] if runs_on is None else [runs_on]
        for ref in refs:
            item = offered.get((ref.kind, ref.id))
            if item is not None and item not in picked:
                picked.append(item)
        told = [item for item in picked if item is not runs_on]
        return ResolvedMentions(agent_id=agent_id, mentions=picked, note=_note(told))

    async def _servers(self, ctx: AuthContext, spec: AgentSpec) -> list[Mentionable]:
        connections = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db,
            connection_ids=[
                ref.connection_id for ref in spec.mcp_servers if isinstance(ref, OrgMcpServerRef)
            ],
            organization_id=ctx.organization_id,
        )
        items: list[Mentionable] = []
        for ref in spec.mcp_servers:
            if isinstance(ref, OrgMcpServerRef):
                connection = connections.get(ref.connection_id)
                if connection is None:
                    continue
                entry = get_entry(connection.catalog_key) if connection.catalog_key else None
                items.append(
                    Mentionable(
                        kind="mcp",
                        id=str(connection.id),
                        name=connection.label or (entry.name if entry else connection.name),
                        detail=f"{tool_prefix(connection.name)}_*",
                        icon=(entry.icon or None) if entry else None,
                    )
                )
            elif isinstance(ref, PersonalMcpServerRef):
                entry = get_entry(ref.catalog_key)
                items.append(
                    Mentionable(
                        kind="mcp",
                        id=ref.catalog_key,
                        name=entry.name if entry else ref.catalog_key,
                        detail=f"{tool_prefix(ref.catalog_key)}_*",
                        icon=(entry.icon or None) if entry else None,
                    )
                )
            else:
                items.append(
                    Mentionable(
                        kind="mcp",
                        id="platform",
                        name=settings.PROJECT_NAME,
                        detail=f"{PLATFORM_MCP_PREFIX}_*",
                    )
                )
        return items

    async def _agents(self, ctx: AuthContext, agent_id: UUID, spec: AgentSpec) -> list[Mentionable]:
        """The chat agent's delegates, then the other published agents the person may run."""
        delegates = {ref.agent_id for ref in spec.subagents} if _bound(spec, "subagents") else set()
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW
        )
        agents, _total = await agent_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=shared or [],
            limit=_AGENTS_OFFERED,
        )
        published = [
            agent
            for agent in agents
            if agent.id != agent_id and agent.current_version_id is not None
        ]
        runnable = await accessible_ids(
            self.db, ctx, published, Perm.AGENTS_RUN, resource_type=AGENT
        )
        offered = [agent for agent in published if agent.id in runnable]
        offered.sort(key=lambda agent: agent.id not in delegates)
        return [
            Mentionable(
                kind="agent",
                id=str(agent.id),
                name=agent.name,
                detail=agent.description,
                slug=agent.slug,
                has_avatar=agent.has_avatar,
                avatar_color=agent.avatar_color,
                delegate=agent.id in delegates,
            )
            for agent in offered
        ]

    async def _knowledge(self, ctx: AuthContext, spec: AgentSpec) -> list[Mentionable]:
        """The knowledge bases, skills and context files the agent reads, where it can read them."""
        items: list[Mentionable] = []
        if _bound(spec, "knowledge"):
            collections = await knowledge_base_repo.get_by_ids(self.db, spec.collection_ids)
            items += [
                Mentionable(kind="collection", id=str(found.id), name=found.name)
                for collection_id in spec.collection_ids
                if (found := collections.get(collection_id)) is not None
                and found.organization_id == ctx.organization_id
            ]
        if _bound(spec, "skills"):
            skills = await skill_repo.get_many(
                self.db, spec.skill_ids, organization_id=ctx.organization_id
            )
            items += [
                Mentionable(kind="skill", id=str(skill.id), name=skill.name)
                for skill_id in spec.skill_ids
                if (skill := skills.get(skill_id)) is not None
            ]
        if _bound(spec, "context"):
            files = await context_repo.get_many(
                self.db, spec.context_ids, organization_id=ctx.organization_id
            )
            items += [
                Mentionable(kind="context", id=str(file.id), name=file.name)
                for context_id in spec.context_ids
                if (file := files.get(context_id)) is not None
            ]
        return items


def _note(mentions: list[Mentionable]) -> str | None:
    """What the model reads about the mentions: names and how to use them, never content."""
    if not mentions:
        return None
    how = {
        "mcp": lambda item: f'MCP server "{item.name}" - use its tools ({item.detail}).',
        "agent": lambda item: (
            f'Agent "{item.name}" - hand the work to this specialist with the `task` tool.'
        ),
        "collection": lambda item: (
            f'Knowledge base "{item.name}" - search it with `search_documents`.'
        ),
        "skill": lambda item: f'Skill "{item.name}" - follow it for this request.',
        "context": lambda item: f'Context file "{item.name}" - use what it says.',
    }
    lines = "\n".join(f"- {how[item.kind](item)}" for item in mentions)
    return f"The person pointed at these for this request; use them:\n{lines}"
