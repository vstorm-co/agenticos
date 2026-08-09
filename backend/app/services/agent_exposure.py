"""Deciding where an agent is available.

One concept covers every place an agent can be reached: an *exposure*. An agent
is available on zero or more surfaces, and each row is one of them. Keeping it
out of :class:`app.agents.spec.AgentSpec` is what makes the two lifecycles
independent - publishing a new version cannot silently change who can reach the
agent, and binding it to a bot cannot mint a version nobody reviewed.

Who may decide this is `agents:publish` **on that agent**, resolved through
:func:`app.services.access.resolve_access` rather than a role gate. Two reasons,
and the second is the one that matters:

*It is the same class of act as publishing.* Both answer "what does the outside
world get to reach", and an author who may freeze a version may say where it
runs.

*It is deliberately not `channels:manage`.* That permission governs the bot -
its token, its webhook, its access policy - and binding an agent changes none of
those. Demanding it would mean only an Admin could put an agent in Slack, while
the Builders who publish agents could not, and the section would be read-only for
exactly the people it is for.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import get as get_capability
from app.agents.capabilities.channel_tools import CHANNEL_TOOLS_CAPABILITY_ID
from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_exposure import AgentExposure, ExposureSurface
from app.db.models.channel_bot import ChannelBot
from app.repositories import agent_environment_repo, agent_exposure_repo, channel_bot_repo
from app.schemas.agent_exposure import (
    ExposureCreate,
    ExposureRead,
    ExposureTarget,
    ExposureTool,
    ExposureUpdate,
    ExposureVariable,
)
from app.schemas.channel_bot import UsageReporting
from app.services.agent_registry import AgentRegistryService
from app.services.channels.directory import PLATFORM_TOOLS
from app.services.channels.formatting import house_style
from app.services.channels.prompt_variables import VARIABLES as PROMPT_VARIABLES

# How many bots one organization can have bound before the picker stops being a
# picker. Far above any real deployment; it exists so the query is bounded.
_MAX_TARGETS = 200

# Platforms an exposure can serve, as the bot rows spell them.
_EXPOSABLE_PLATFORMS = frozenset(surface.value for surface in ExposureSurface)


def _surface_for(bot: ChannelBot) -> ExposureSurface:
    """The exposure surface a bot serves.

    Raises:
        BadRequestError: If the bot is on a platform no exposure covers. Better
            here than at mention time, where the binding would exist, look
            correct in the Builder, and never route anything.
    """
    try:
        return ExposureSurface(bot.platform)
    except ValueError as exc:
        raise BadRequestError(
            message=f"Agents cannot be exposed on {bot.platform} yet",
            details={"platform": bot.platform},
        ) from exc


def _lookups_for(surface: ExposureSurface) -> list[ExposureTool]:
    """The channel lookups this platform can answer, as the form offers them.

    Registry order, and registry text: the description a person reads while
    deciding whether to grant a tool is the one the model reads before deciding
    to call it. Anything the platform has no equivalent for is left out rather
    than offered and refused - see `PLATFORM_TOOLS`.
    """
    available = PLATFORM_TOOLS.get(surface.value, ())
    return [
        ExposureTool(id=tool.id, name=tool.name, description=tool.description)
        for tool in get_capability(CHANNEL_TOOLS_CAPABILITY_ID).tools
        if tool.id in available
    ]


def _variables_for(surface: ExposureSurface) -> list[ExposureVariable]:
    """The placeholders this platform can fill in.

    Keyed on the same `PLATFORM_TOOLS` the lookups are, because they are
    answered by the same calls: `{channel_name}` is `channel_details` and
    `{member_list}` is `channel_members`. Telegram implements both, so it
    offers every placeholder even though it offers only two of the four tools -
    which is the point of deriving this rather than writing a second list.
    """
    available = PLATFORM_TOOLS.get(surface.value, ())
    answered = {
        "get_channel_info": {"channel_name", "channel_purpose", "channel_topic", "member_count"},
        "list_channel_members": {"member_list"},
    }
    fillable = {name for tool, names in answered.items() if tool in available for name in names}
    return [
        ExposureVariable(name=variable.name, description=variable.description)
        for variable in PROMPT_VARIABLES
        if variable.name in fillable
    ]


def _checked_tools(tools: list[str], surface: ExposureSurface) -> list[str]:
    """The granted lookups, in registry order, or a refusal naming what is wrong.

    Ordered rather than stored as sent, so two saves that grant the same things
    produce the same row and an audit entry that differs says something changed.

    Raises:
        BadRequestError: If a tool is not one this capability registers, or is
            one this platform cannot answer. Refused rather than dropped: a
            request that silently grants three of the four it asked for is one
            whose form will show the fourth unticked next time somebody looks,
            with nothing saying why.
    """
    offered = {tool.id for tool in _lookups_for(surface)}
    unknown = sorted(set(tools) - offered)
    if unknown:
        raise BadRequestError(
            message=f"{surface.value} cannot answer: {', '.join(unknown)}",
            details={"surface": surface.value, "tools": unknown, "available": sorted(offered)},
        )
    return [tool.id for tool in _lookups_for(surface) if tool.id in set(tools)]


def _update_action(changes: dict[str, Any]) -> str:
    """What to call this edit in the trail.

    Pausing and resuming get their own names because they are the two people
    search for after an agent stopped - or started - answering somewhere.
    """
    if changes.get("is_active") is True:
        return "agent.exposure_resumed"
    if changes.get("is_active") is False:
        return "agent.exposure_paused"
    return "agent.exposure_updated"


class AgentExposureService:
    """Manage where an organization's agents are available."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[ExposureRead]:
        """Every place this agent is available, named the way a person reads it.

        Requires only `agents:view`: seeing where an agent answers is part of
        understanding what it is, and hiding it from someone who can already read
        the agent would only make the Builder lie by omission.
        """
        agent = await self.agents.get(ctx, agent_id)
        exposures = await agent_exposure_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        names = await self._bot_names(ctx)
        return [self._read(exposure, names) for exposure in exposures]

    @staticmethod
    def _read(exposure: AgentExposure, names: dict[UUID, str]) -> ExposureRead:
        """One binding as the Builder shows it, lookups included."""
        surface = ExposureSurface(exposure.surface)
        return ExposureRead(
            id=exposure.id,
            agent_id=exposure.agent_id,
            surface=surface,
            channel_bot_id=exposure.channel_bot_id,
            # A bot deleted concurrently would take its bindings with it, so
            # this is the window between the two queries rather than a state
            # anyone can persist. Naming it beats rendering a blank row.
            channel_bot_name=names.get(exposure.channel_bot_id, "(removed)"),
            environment_id=exposure.environment_id,
            session_scope=exposure.session_scope,
            prompt=exposure.prompt,
            tools=list(exposure.tools or []),
            available_tools=_lookups_for(surface),
            available_variables=_variables_for(surface),
            usage_reporting=UsageReporting.model_validate(exposure.usage_reporting or {}),
            is_active=exposure.is_active,
            created_at=exposure.created_at,
        )

    async def targets(self, ctx: AuthContext, agent_id: UUID) -> list[ExposureTarget]:
        """The bots this agent could be bound to.

        Scoped to the agent so the route stays a per-resource one, and so the
        answer is empty for somebody who cannot reach the agent in the first
        place. Bots on a platform no exposure covers are left out rather than
        offered and then refused.

        So are bots another agent already answers on. A bot is one identity in
        the chat and serves one agent, so offering a taken one is offering a
        choice that ends in a 409 - and the picker is the place that knows,
        because the person choosing does not.
        """
        agent = await self.agents.get(ctx, agent_id)
        bots = await channel_bot_repo.list_for_org(
            self.db, organization_id=ctx.organization_id, limit=_MAX_TARGETS
        )
        # Paused bindings included: one still occupies `uq_exposure_bot`, so a
        # bot filtered on "who is answering" would be offered and then refused.
        taken = await agent_exposure_repo.bound_agent_by_bot(
            self.db, channel_bot_ids=[bot.id for bot in bots]
        )
        return [
            ExposureTarget(
                id=bot.id,
                platform=ExposureSurface(bot.platform),
                name=bot.name,
                is_active=bot.is_active,
            )
            for bot in bots
            if bot.platform in _EXPOSABLE_PLATFORMS
            # This agent's own binding stays in the list: the caller filters it
            # out to know which bots are *already* served, and dropping it here
            # would make "bound" and "taken by somebody else" the same absence.
            and taken.get(bot.id, agent.id) == agent.id
        ]

    async def create(self, ctx: AuthContext, agent_id: UUID, data: ExposureCreate) -> AgentExposure:
        """Make an agent available through one of the organization's bots.

        Raises:
            NotFoundError: If the agent is not reachable by this caller, or the
                bot is not in this organization. A bot from another tenant is
                reported as missing rather than forbidden, so ids stay
                unprobeable - the same rule the agent routes follow.
            BadRequestError: If the bot's platform has no exposure surface.
            AlreadyExistsError: If this agent is already bound to this bot.
                Silently returning the existing row would make an accidental
                second bind indistinguishable from the first, and the caller
                would never learn the two requests were not both effective.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        bot = await channel_bot_repo.get_for_org(
            self.db, data.channel_bot_id, organization_id=ctx.organization_id
        )
        if bot is None:
            raise NotFoundError(
                message="Channel bot not found",
                details={"channel_bot_id": str(data.channel_bot_id)},
            )
        surface = _surface_for(bot)

        # Any row on this bot, by anybody, and not just an active one: a paused
        # binding still occupies the unique constraint, and letting the insert
        # reach it would turn a question the service can answer into an
        # IntegrityError nobody can read.
        taken = await agent_exposure_repo.bound_to_bot(self.db, channel_bot_id=bot.id)
        if taken is not None and taken.agent_id == agent.id:
            raise AlreadyExistsError(
                message=f"'{agent.name}' is already bound to {bot.name}",
                details={"exposure_id": str(taken.id), "is_active": taken.is_active},
            )
        if taken is not None:
            # A bot user is one identity in the chat - the same avatar and the
            # same name whichever agent replied - so it answers as one agent.
            # The way to have two is two bots, and saying so is the whole value
            # of this refusal. The other binding's id is not carried: it is
            # somebody else's row and there is nothing the caller can do with it.
            raise AlreadyExistsError(
                message=(
                    f"{bot.name} already serves another agent. A bot answers as one "
                    "agent - register a second bot for this one."
                ),
                details={"channel_bot_id": str(bot.id)},
            )

        if data.environment_id is not None:
            await self._environment_of(ctx, agent.id, data.environment_id)

        exposure = await agent_exposure_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            surface=surface.value,
            channel_bot_id=bot.id,
            created_by_user_id=ctx.user_id,
            environment_id=data.environment_id,
            # The platform's own style, as the binding's starting text rather
            # than something applied invisibly at run time. It is what the
            # agent will be told, so it is what somebody editing it should see
            # and be able to change. The cost is that it is a copy: improving
            # the default later does not reach a binding that already exists.
            prompt=house_style(surface.value),
            session_scope=data.session_scope,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.exposed",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "exposure_id": str(exposure.id),
                "surface": surface.value,
                "channel_bot_id": str(bot.id),
            },
        )
        return exposure

    async def update(
        self, ctx: AuthContext, agent_id: UUID, exposure_id: UUID, data: ExposureUpdate
    ) -> AgentExposure:
        """Pause, resume, or rebind a binding to another environment.

        Only the fields the caller actually sent are applied. Pausing a binding
        must not silently move it back to the default environment, and a schema
        default cannot tell "leave it alone" from "clear it" - so the distinction
        is read off the request rather than inferred from `None`.

        Raises:
            BadRequestError: If `tools` names a lookup this binding's platform
                cannot answer.
        """
        exposure = await self._owned(ctx, agent_id, exposure_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("environment_id") is not None:
            await self._environment_of(ctx, agent_id, changes["environment_id"])
        if changes.get("tools") is not None:
            # Checked against the platform this binding actually serves, not
            # against the whole capability: what a Telegram bot may be asked is
            # a shorter list than what a Mattermost bot may, and a granted tool
            # that can only ever refuse is a checkbox that lies.
            changes["tools"] = _checked_tools(changes["tools"], ExposureSurface(exposure.surface))
        updated = await agent_exposure_repo.update(self.db, exposure=exposure, update_data=changes)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=_update_action(changes),
            target_type="agent",
            target_id=str(agent_id),
            # The values, not just the keys. "Somebody changed the binding" is not
            # an audit entry anyone can act on a month later.
            details={"exposure_id": str(exposure.id), "changes": changes},
        )
        return updated

    async def delete(self, ctx: AuthContext, agent_id: UUID, exposure_id: UUID) -> None:
        """Remove a binding entirely - the agent stops answering there."""
        exposure = await self._owned(ctx, agent_id, exposure_id)
        await agent_exposure_repo.delete(self.db, exposure)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.unexposed",
            target_type="agent",
            target_id=str(agent_id),
            details={"exposure_id": str(exposure_id), "surface": exposure.surface},
        )

    async def _environment_of(self, ctx: AuthContext, agent_id: UUID, environment_id: UUID) -> None:
        """Refuse an environment that is not this agent's.

        Without this, an environment id from another agent - even the caller's
        own - would bind a bot to a version of something else entirely, and the
        runner would resolve it as "not found" only after the message arrived.
        """
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent_id:
            raise NotFoundError(
                message="Environment not found",
                details={"environment_id": str(environment_id)},
            )

    async def _owned(self, ctx: AuthContext, agent_id: UUID, exposure_id: UUID) -> AgentExposure:
        """The exposure, if it belongs to this agent and this caller may change it.

        Both halves are checked. The organization scope alone would let somebody
        pass another agent's exposure id to an agent they *can* publish and
        unbind it, which is a cross-resource escalation inside one tenant.

        Raises:
            NotFoundError: If the exposure is missing, in another organization,
                or on a different agent than the one in the path.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        exposure = await agent_exposure_repo.get(
            self.db, exposure_id, organization_id=ctx.organization_id
        )
        if exposure is None or exposure.agent_id != agent.id:
            raise NotFoundError(
                message="Exposure not found", details={"exposure_id": str(exposure_id)}
            )
        return exposure

    async def _bot_names(self, ctx: AuthContext) -> dict[UUID, str]:
        bots = await channel_bot_repo.list_for_org(
            self.db, organization_id=ctx.organization_id, limit=_MAX_TARGETS
        )
        return {bot.id: bot.name for bot in bots}
