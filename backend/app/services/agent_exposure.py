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
    ExposureUpdate,
)
from app.services.agent_registry import AgentRegistryService

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
        return [
            ExposureRead(
                id=exposure.id,
                agent_id=exposure.agent_id,
                surface=ExposureSurface(exposure.surface),
                channel_bot_id=exposure.channel_bot_id,
                # A bot deleted concurrently would take its bindings with it, so
                # this is the window between the two queries rather than a state
                # anyone can persist. Naming it beats rendering a blank row.
                channel_bot_name=names.get(exposure.channel_bot_id, "(removed)"),
                environment_id=exposure.environment_id,
                session_scope=exposure.session_scope,
                prompt=exposure.prompt,
                is_active=exposure.is_active,
                created_at=exposure.created_at,
            )
            for exposure in exposures
        ]

    async def targets(self, ctx: AuthContext, agent_id: UUID) -> list[ExposureTarget]:
        """The bots this agent could be bound to.

        Scoped to the agent so the route stays a per-resource one, and so the
        answer is empty for somebody who cannot reach the agent in the first
        place. Bots on a platform no exposure covers are left out rather than
        offered and then refused.
        """
        await self.agents.get(ctx, agent_id)
        bots = await channel_bot_repo.list_for_org(
            self.db, organization_id=ctx.organization_id, limit=_MAX_TARGETS
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

        # Any row, not just an active one: a paused binding still occupies the
        # unique constraint, and letting the insert reach it would turn a
        # question the service can answer into an IntegrityError nobody can read.
        existing = await agent_exposure_repo.get_for_bot(
            self.db, agent_id=agent.id, channel_bot_id=bot.id
        )
        if existing is not None:
            raise AlreadyExistsError(
                message=f"'{agent.name}' is already bound to {bot.name}",
                details={"exposure_id": str(existing.id), "is_active": existing.is_active},
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
        """
        exposure = await self._owned(ctx, agent_id, exposure_id)
        changes = data.model_dump(exclude_unset=True)
        if changes.get("environment_id") is not None:
            await self._environment_of(ctx, agent_id, changes["environment_id"])
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
