"""`@`-mentions: what a person may point an agent at, and what reaches the model (#2189).

A mention never widens what an agent may reach, and never changes which agent
answers. What the composer offers is what the chat's agent already has - its MCP
servers, its knowledge bases, skills and context files, and, where it delegates,
the specialists it delegates to. A frame is resolved against that same list on the
server, so an id the person could not have picked is dropped rather than trusted,
and the run still checks every access it would have checked without the mention.

What reaches the model is a short note naming each thing and how to use it, never
the thing's content.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import get as get_capability
from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.mcp import PLATFORM_MCP_PREFIX, tool_prefix
from app.agents.spec import (
    AgentSpec,
    OrgMcpServerRef,
    PersonalMcpServerRef,
)
from app.core.config import settings
from app.core.permissions import AuthContext
from app.repositories import agent as agent_repo
from app.repositories import context as context_repo
from app.repositories import knowledge_base as knowledge_base_repo
from app.repositories import mcp_connection as mcp_connection_repo
from app.repositories import skill as skill_repo
from app.schemas.mention import Mentionable, MentionRef
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_catalog import get_entry

INLINE_PREFIX = "inline:"
"""How an inline specialist is named in a mention: it has no row, only a name."""


@dataclass(frozen=True)
class ResolvedMentions:
    """A frame's mentions, checked: what the transcript shows and what the model is told."""

    mentions: list[Mentionable]
    """What the transcript shows as chips, in the order they were picked."""

    note: str | None
    """Appended to the person's message for the model; `None` when nothing was mentioned."""


def _bound(spec: AgentSpec, capability_id: str) -> bool:
    return any(binding.id == capability_id and binding.enabled for binding in spec.capabilities)


def _delegation(spec: AgentSpec) -> SubagentsConfig | None:
    """The delegation capability's config, or `None` where the agent does not delegate."""
    binding = next(
        (one for one in spec.capabilities if one.id == "subagents" and one.enabled), None
    )
    return None if binding is None else SubagentsConfig.model_validate(binding.config or {})


class MentionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def available(
        self, ctx: AuthContext, agent_id: UUID, *, draft: bool = False
    ) -> list[Mentionable]:
        """Everything the person may point this agent at, servers first.

        `draft` reads the Builder's draft rather than the published version - what
        its test panel runs, so what it offers is what that run can reach.

        Raises:
            NotFoundError, AuthorizationError: If the caller may not run the agent,
                or, for the draft, may not edit it.
        """
        return await self._offered(ctx, await self._spec(ctx, agent_id, draft=draft))

    async def resolve(
        self, ctx: AuthContext, agent_id: UUID, refs: list[MentionRef], *, draft: bool = False
    ) -> ResolvedMentions:
        """A frame's mentions against what the person could have picked.

        The chat's agent answers whatever is mentioned: an agent named here is a
        specialist it hands work to, never a switch of who replies.
        """
        if not refs:
            return ResolvedMentions(mentions=[], note=None)
        spec = await self._spec(ctx, agent_id, draft=draft)
        offered = {(item.kind, item.id): item for item in await self._offered(ctx, spec)}
        picked: list[Mentionable] = []
        for ref in refs:
            item = offered.get((ref.kind, ref.id))
            if item is not None and item not in picked:
                picked.append(item)
        tools = {item.id: names for item, names in _capabilities(spec)}
        return ResolvedMentions(
            mentions=picked,
            note=_note(
                picked,
                tools,
                hand_off=_tool_name(spec, "subagents", "task"),
                search=_tool_name(spec, "knowledge", "search_documents"),
            ),
        )

    async def _spec(self, ctx: AuthContext, agent_id: UUID, *, draft: bool) -> AgentSpec:
        registry = AgentRegistryService(self.db)
        if draft:
            _agent, spec = await registry.get_draft_spec(ctx, agent_id)
            return spec
        _agent, spec, _version = await registry.get_runnable_spec(ctx, agent_id)
        return spec

    async def _offered(self, ctx: AuthContext, spec: AgentSpec) -> list[Mentionable]:
        return [
            *await self._servers(ctx, spec),
            *(item for item, _tools in _capabilities(spec)),
            *await self._delegates(ctx, spec),
            *await self._knowledge(ctx, spec),
        ]

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
                # Disabled since publish: the run leaves its tools out, so a chip
                # pointing at it would send the model after tools it lacks.
                if connection is None or not connection.is_enabled:
                    continue
                entry = get_entry(connection.catalog_key) if connection.catalog_key else None
                items.append(
                    Mentionable(
                        kind="mcp",
                        id=str(connection.id),
                        name=connection.label or (entry.name if entry else connection.name),
                        detail=f"{tool_prefix(connection.name)}_*",
                        icon=(entry.icon or None) if entry else None,
                        host=_host(connection.url),
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
                        host=_host(entry.url) if entry else None,
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

    async def _delegates(self, ctx: AuthContext, spec: AgentSpec) -> list[Mentionable]:
        """Who the agent hands work to: its published delegates, then its inline specialists.

        Nothing where the delegation capability is off - an agent it cannot hand
        work to is not something it can be pointed at. Every pinned delegate is
        offered, whoever asks: `AGENTS_RUN` on it was checked when the parent was
        published, and the run does not ask again (`_resolve_delegate`), so one
        hidden here would still be handed work - only never by name.
        """
        config = _delegation(spec)
        if config is None:
            return []
        rows = await agent_repo.get_many(
            self.db,
            [ref.agent_id for ref in spec.subagents],
            organization_id=ctx.organization_id,
        )
        published = [
            agent for ref in spec.subagents if (agent := rows.get(ref.agent_id)) is not None
        ]
        return [
            *(
                Mentionable(
                    kind="agent",
                    id=str(agent.id),
                    name=agent.name,
                    detail=agent.description,
                    slug=agent.slug,
                    has_avatar=agent.has_avatar,
                    avatar_color=agent.avatar_color,
                )
                for agent in published
            ),
            *(
                Mentionable(
                    kind="agent",
                    id=f"{INLINE_PREFIX}{specialist.name}",
                    name=specialist.name,
                    detail=specialist.description,
                )
                for specialist in config.inline
            ),
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


def _capabilities(spec: AgentSpec) -> list[tuple[Mentionable, list[str]]]:
    """The switched-on capabilities that give the agent tools, as a person knows them.

    A capability rather than its tools: `@Sandbox` is what somebody means, not
    `ls` and `grep`. The tools come along for the note, under the names the
    binding gives them - a rename is the name its model sees.
    """
    items: list[tuple[Mentionable, list[str]]] = []
    for binding in spec.capabilities:
        if not binding.enabled:
            continue
        definition = get_capability(binding.id)
        tools = [tool.name for tool in definition.effective_tools(binding.tool_overrides)]
        if not tools:
            continue
        item = Mentionable(
            kind="capability",
            id=definition.id,
            name=definition.name,
            detail=definition.description.strip().split("\n", 1)[0] or None,
            icon=definition.tools[0].id,
        )
        items.append((item, tools))
    return items


def _tool_name(spec: AgentSpec, capability_id: str, tool_id: str) -> str:
    """The name a binding gives one of its capability's tools - what its model calls."""
    binding = next((one for one in spec.capabilities if one.id == capability_id), None)
    overrides = binding.tool_overrides if binding is not None else {}
    named = get_capability(capability_id).effective_tools(overrides)
    return next((tool.name for tool in named if tool.id == tool_id), tool_id)


def _note(
    mentions: list[Mentionable],
    tools: dict[str, list[str]],
    *,
    hand_off: str,
    search: str,
) -> str | None:
    """What the model reads about the mentions: names and how to use them, never content.

    Tools are named as the binding names them: a renamed `task` or
    `search_documents` is the only name the model was given.
    """
    if not mentions:
        return None
    how = {
        "mcp": lambda item: f'MCP server "{item.name}" - use its tools ({item.detail}).',
        "capability": lambda item: (
            f'Capability "{item.name}" - use its tools '
            f"({', '.join(tools.get(item.id, []))}) for this request."
        ),
        "agent": lambda item: (
            f'Agent "{item.name}" - hand the work to this specialist with the `{hand_off}` tool.'
        ),
        "collection": lambda item: f'Knowledge base "{item.name}" - search it with `{search}`.',
        "skill": lambda item: f'Skill "{item.name}" - follow it for this request.',
        "context": lambda item: f'Context file "{item.name}" - use what it says.',
    }
    lines = "\n".join(f"- {how[item.kind](item)}" for item in mentions)
    return f"The person pointed at these for this request; use them:\n{lines}"


def _host(url: str) -> str | None:
    """The host of an MCP server's address, or None for one without."""
    return urlsplit(url).hostname or None
