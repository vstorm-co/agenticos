"""Named environments of an agent - create, promote, rename, remove.

The registry owns what a version *is*; this service owns which one answers
under which name. It sits beside `AgentExposureService` on purpose: both
manage operational state that publishing deliberately does not touch, and both
hand every access decision to the registry, which reads the caller's role and
grants and reports refusals as "not found" so agent ids stay unprobeable.

What this service refuses is as deliberate as what it allows:

* No environment without a version. An unpinned environment would be a name
  that answers with nothing, and the first message routed to it would fail far
  from the form that created it.
* The default is managed by publish, not here. Deleting it, renaming another
  row onto it, or hand-toggling `is_default` would put "what does a plain
  surface get" into two hands, and they would eventually disagree.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.updates import cleared, writable
from app.repositories import agent_environment_repo, agent_repo, organization_secret_repo
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentRead, EnvironmentUpdate
from app.services.agent_registry import AgentRegistryService

logger = logging.getLogger(__name__)


class AgentEnvironmentService:
    """Manages which published version of an agent each named environment runs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    async def list_for_agent(self, ctx: AuthContext, agent_id: UUID) -> list[EnvironmentRead]:
        """Every environment of this agent, with the version number a person
        would look for in the history.

        Requires only `agents:view`, like the exposure listing: which build
        answers where is part of understanding the agent.
        """
        agent = await self.agents.get(ctx, agent_id)
        environments = await agent_environment_repo.list_for_agent(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        numbers = await self._version_numbers(ctx, environments)
        return [
            EnvironmentRead(
                id=environment.id,
                agent_id=environment.agent_id,
                name=environment.name,
                version_id=environment.version_id,
                version=numbers[environment.version_id],
                is_default=environment.is_default,
                logfire_token_secret_id=environment.logfire_token_secret_id,
                service_name=environment.service_name,
                created_at=environment.created_at,
            )
            for environment in environments
        ]

    async def create(
        self, ctx: AuthContext, agent_id: UUID, data: EnvironmentCreate
    ) -> AgentEnvironment:
        """Add a named environment, pinned to a version from birth.

        Raises:
            NotFoundError: If the agent is not reachable by this caller, or the
                named version is not this agent's.
            BadRequestError: If the agent has never been published - there is
                no version to pin, so there is nothing an environment could
                mean yet.
            AlreadyExistsError: If the name is taken on this agent.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        if agent.current_version_id is None:
            raise BadRequestError(
                message=f"Publish '{agent.name}' before adding environments - "
                "an environment is a pointer at a published version.",
                details={"agent_id": str(agent.id)},
            )
        if await agent_environment_repo.get_by_name(self.db, agent_id=agent.id, name=data.name):
            raise AlreadyExistsError(
                message=f"'{agent.name}' already has an environment named '{data.name}'",
                details={"agent_id": str(agent.id), "name": data.name},
            )
        version = await self._version_of(ctx, agent, data.version_id or agent.current_version_id)
        if data.logfire_token_secret_id is not None:
            await self._check_logfire_secret(ctx, data.logfire_token_secret_id)

        environment = await agent_environment_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            name=data.name,
            version_id=version.id,
            created_by_user_id=ctx.user_id,
            logfire_token_secret_id=data.logfire_token_secret_id,
            service_name=data.service_name,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.environment_created",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "environment_id": str(environment.id),
                "name": environment.name,
                "version": version.version,
            },
        )
        return environment

    async def update(
        self, ctx: AuthContext, agent_id: UUID, environment_id: UUID, data: EnvironmentUpdate
    ) -> AgentEnvironment:
        """Repoint an environment at another version, or rename it.

        Repointing *is* promotion: "promote v12 to production" is this call
        with production's id and v12. It is audited as such, because "who put
        this version in front of users" is the first question after a bad one.

        Raises:
            NotFoundError: If the environment is not this agent's, or the named
                version is not.
            BadRequestError: If the target is the default environment being
                renamed - its name is part of the publish contract - or the
                update names nothing to change.
            AlreadyExistsError: If the new name is taken on this agent.
        """
        agent, environment = await self._get(ctx, agent_id, environment_id)
        # Before `writable`, which drops it: an environment is always pinned, so
        # `version_id: null` is a request to refuse rather than a value to write -
        # and dropping it first turned that refusal into "Nothing to change", which
        # is true of the row and useless to whoever asked.
        if cleared(data, "version_id"):
            raise BadRequestError(
                message="An environment is always pinned - point it at a version.",
                details={"environment_id": str(environment.id)},
            )
        changes = writable(data, over=AgentEnvironment)
        if not changes:
            raise BadRequestError(message="Nothing to change", details={})

        if changes.get("logfire_token_secret_id") is not None:
            await self._check_logfire_secret(ctx, changes["logfire_token_secret_id"])

        if "name" in changes and environment.is_default:
            raise BadRequestError(
                message="The default environment keeps its name - publish manages it.",
                details={"environment_id": str(environment.id)},
            )
        if (
            "name" in changes
            and changes["name"] != environment.name
            and await agent_environment_repo.get_by_name(
                self.db, agent_id=agent.id, name=changes["name"]
            )
        ):
            raise AlreadyExistsError(
                message=f"'{agent.name}' already has an environment named '{changes['name']}'",
                details={"agent_id": str(agent.id), "name": changes["name"]},
            )

        version: AgentVersion | None = None
        if "version_id" in changes:
            if changes["version_id"] is None:
                raise BadRequestError(
                    message="An environment is always pinned - point it at a version.",
                    details={"environment_id": str(environment.id)},
                )
            version = await self._version_of(ctx, agent, changes["version_id"])

        environment = await agent_environment_repo.update(
            self.db, environment=environment, update_data=changes
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.environment_promoted" if version else "agent.environment_renamed",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "environment_id": str(environment.id),
                "name": environment.name,
                **({"version": version.version} if version else {}),
            },
        )
        return environment

    async def delete(self, ctx: AuthContext, agent_id: UUID, environment_id: UUID) -> None:
        """Remove a named environment.

        Exposures pointing at it fall back to the default (`environment_id`
        becomes NULL on delete), which is the least surprising failure: the
        bot keeps answering, with what everyone else gets.

        Raises:
            NotFoundError: If the environment is not this agent's.
            BadRequestError: If it is the default - an agent without a default
                is an agent plain surfaces cannot run.
        """
        agent, environment = await self._get(ctx, agent_id, environment_id)
        if environment.is_default:
            raise BadRequestError(
                message="The default environment cannot be removed - it is what "
                "every surface that names no environment gets.",
                details={"environment_id": str(environment.id)},
            )
        name = environment.name
        await agent_environment_repo.delete(self.db, environment=environment)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.environment_deleted",
            target_type="agent",
            target_id=str(agent.id),
            details={"environment_id": str(environment_id), "name": name},
        )

    async def _get(
        self, ctx: AuthContext, agent_id: UUID, environment_id: UUID
    ) -> tuple[Agent, AgentEnvironment]:
        """The agent and one of its environments, or "not found".

        The environment must belong to the agent in the URL: an id from another
        agent - even the caller's own - resolving here would let one agent's
        routes act on another's state.
        """
        agent = await self.agents.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        environment = await agent_environment_repo.get(
            self.db, environment_id, organization_id=ctx.organization_id
        )
        if environment is None or environment.agent_id != agent.id:
            raise NotFoundError(
                message="Environment not found",
                details={"environment_id": str(environment_id)},
            )
        return agent, environment

    async def _check_logfire_secret(self, ctx: AuthContext, secret_id: UUID) -> None:
        """Refuse a token the organization does not hold, or one for something else.

        Checked here, where the person choosing can fix it: the runner treats a
        missing token as "run untraced" rather than an error, so a wrong choice
        would otherwise surface as silence in a Logfire project.
        """
        row = await organization_secret_repo.get(
            self.db, secret_id, organization_id=ctx.organization_id
        )
        if row is None:
            raise BadRequestError(
                message="That key is not in this organization's vault",
                details={"logfire_token_secret_id": str(secret_id)},
            )
        if row.purpose != "logfire":
            raise BadRequestError(
                message=f"That key is for {row.purpose}, not Logfire",
                details={"purpose": row.purpose},
            )

    async def _version_of(self, ctx: AuthContext, agent: Agent, version_id: UUID) -> AgentVersion:
        """One of *this agent's* versions, or "not found"."""
        version = await agent_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        if version is None or version.agent_id != agent.id:
            raise NotFoundError(
                message="Version not found", details={"version_id": str(version_id)}
            )
        return version

    async def _version_numbers(
        self, ctx: AuthContext, environments: list[AgentEnvironment]
    ) -> dict[UUID, int]:
        """The version number behind each pinned id, for the listing.

        A pinned version can only be missing inside the window between reading
        the environments and reading the versions; 0 names that window rather
        than crashing the whole listing on it.
        """
        numbers: dict[UUID, int] = {}
        for version_id in {environment.version_id for environment in environments}:
            version = await agent_repo.get_version(
                self.db, version_id, organization_id=ctx.organization_id
            )
            numbers[version_id] = version.version if version else 0
        return numbers
