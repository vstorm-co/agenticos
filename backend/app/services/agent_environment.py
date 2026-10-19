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
* No connection override that names something the organization does not hold,
  or that lends a secret the caller cannot see. An override is a binding the
  spec does not carry, so it is checked the way publish checks a binding.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import (
    AgentEnvironment,
    AgentEnvironmentConnection,
    ConnectionKind,
)
from app.db.updates import cleared, writable
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    agent_run_repo,
    artifact_repo,
    eval_run_repo,
    mcp_connection_repo,
    organization_secret_repo,
)
from app.schemas.agent_environment import (
    EnvironmentConnectionRead,
    EnvironmentConnectionWrite,
    EnvironmentCreate,
    EnvironmentRead,
    EnvironmentUpdate,
)
from app.services.access import SECRET, resolve_access
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
        # What "pinned" costs, counted once for the whole listing: an environment
        # three versions behind is a decision somebody made or a thing somebody
        # forgot, and the panel cannot say which without the number.
        newest = await agent_repo.count_versions(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        overrides: dict[UUID, list[EnvironmentConnectionRead]] = {}
        for row in await agent_environment_repo.list_connections(
            self.db,
            environment_ids=[environment.id for environment in environments],
            organization_id=ctx.organization_id,
        ):
            overrides.setdefault(row.environment_id, []).append(
                EnvironmentConnectionRead(
                    kind=ConnectionKind(row.kind).value,
                    production_id=row.production_id,
                    test_id=row.test_id,
                )
            )
        return [
            EnvironmentRead(
                id=environment.id,
                agent_id=environment.agent_id,
                name=environment.name,
                version_id=environment.version_id,
                version=numbers[environment.version_id],
                is_default=environment.is_default,
                tracks_latest=environment.tracks_latest,
                behind_by=max(newest - numbers[environment.version_id], 0),
                logfire_token_secret_id=environment.logfire_token_secret_id,
                service_name=environment.service_name,
                connections=overrides.get(environment.id, []),
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
        connections = await self._checked_connections(ctx, data.connections)

        environment = await agent_environment_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent.id,
            name=data.name,
            version_id=version.id,
            tracks_latest=data.tracks_latest,
            created_by_user_id=ctx.user_id,
            logfire_token_secret_id=data.logfire_token_secret_id,
            service_name=data.service_name,
        )
        if connections:
            await agent_environment_repo.replace_connections(
                self.db,
                environment_id=environment.id,
                organization_id=ctx.organization_id,
                connections=connections,
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
                "connections": len(connections),
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
        changes = writable(data, over=AgentEnvironment, exclude={"connections"})
        if not changes and data.connections is None:
            raise BadRequestError(message="Nothing to change", details={})
        if data.connections and environment.is_default:
            raise BadRequestError(
                message=(
                    "The default environment runs the connections the spec binds - "
                    "add test connections to a named environment such as staging."
                ),
                details={"environment_id": str(environment.id)},
            )
        connections = (
            None
            if data.connections is None
            else await self._checked_connections(ctx, data.connections)
        )

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

        replaced_version_id = environment.version_id
        version: AgentVersion | None = None
        if "version_id" in changes:
            version = await self._version_of(ctx, agent, changes["version_id"])
        elif changes.get("tracks_latest") is True and agent.current_version_id is not None:
            # Switching an environment to "follows latest" adopts the newest
            # version now rather than at the next publish. The alternative is a
            # mode that claims to follow and does not until something else
            # happens, which is the kind of half-true state this whole setting
            # exists to remove.
            newest = await agent_repo.newest_version(
                self.db, agent_id=agent.id, organization_id=ctx.organization_id
            )
            if newest is not None and newest.id != environment.version_id:
                changes["version_id"] = newest.id
                version = newest

        if changes:
            environment = await agent_environment_repo.update(
                self.db, environment=environment, update_data=changes
            )
        if connections is not None:
            await agent_environment_repo.replace_connections(
                self.db,
                environment_id=environment.id,
                organization_id=ctx.organization_id,
                connections=connections,
            )
        if version is not None:
            await AgentRegistryService(self.db).withdraw_creator_consent(ctx, agent)
        if version is not None and version.id != replaced_version_id:
            from app.services.eval_suite import EvalSuiteService

            await EvalSuiteService(self.db).environment_promoted(
                ctx,
                agent=agent,
                environment=environment,
                version=version,
                replaced_version_id=replaced_version_id,
            )
        if environment.is_default and version is not None:
            # The denormalized pointer is this environment's, so promoting the
            # default *is* the deploy every surface naming no environment reads.
            # Publish used to keep the two in step by moving both; now that a
            # publish moves neither, this is where they stay in step.
            await agent_repo.update(
                self.db, agent=agent, update_data={"current_version_id": environment.version_id}
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.environment_promoted" if version else "agent.environment_updated",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "environment_id": str(environment.id),
                "name": environment.name,
                "fields": sorted([*changes, *(["connections"] if connections is not None else [])]),
                **({"version": version.version} if version else {}),
            },
        )
        return environment

    async def delete(self, ctx: AuthContext, agent_id: UUID, environment_id: UUID) -> None:
        """Remove a named environment.

        Exposures pointing at it fall back to the default (`environment_id`
        becomes NULL on delete), which is the least surprising failure: the
        bot keeps answering, with what everyone else gets. Its artifacts do not
        fall back: they stay readable and lose their publisher, the way an
        agent's do when the agent is deleted, so the default environment's page
        of the same name is never the one they collide with.

        Raises:
            NotFoundError: If the environment is not this agent's.
            BadRequestError: If it is the default - an agent without a default
                is an agent plain surfaces cannot run.
            ConcurrentChangeError: If a run of it is still running or parked on
                an approval, or an eval run in it is queued or running. Deleting
                the row sets that run's `environment_id` to null, which reads as
                the default - so a staging run still working, or resumed after a
                decision, would publish its pages over production's, and an eval
                run would go on against production's connections. It is refused
                until the run ends.
        """
        agent, environment = await self._get(ctx, agent_id, environment_id)
        if environment.is_default:
            raise BadRequestError(
                message="The default environment cannot be removed - it is what "
                "every surface that names no environment gets.",
                details={"environment_id": str(environment.id)},
            )
        # Locked first, so no run can start in it between the count and the
        # delete: the count would miss it, and the delete would null its
        # environment while it still runs.
        await agent_environment_repo.lock(self.db, environment.id)
        unfinished = await agent_run_repo.count_unfinished_in_environment(
            self.db, environment_id=environment.id, organization_id=ctx.organization_id
        )
        if unfinished:
            raise ConcurrentChangeError(
                message=(
                    f"{unfinished} run(s) in {environment.name!r} are still running or "
                    "waiting for an approval. Remove it once they finish, or stop them first."
                ),
                details={"environment_id": str(environment.id), "unfinished": unfinished},
            )
        evals = await eval_run_repo.count_live_in_environment(
            self.db, environment_id=environment.id, organization_id=ctx.organization_id
        )
        if evals:
            raise ConcurrentChangeError(
                message=(
                    f"{evals} eval run(s) in {environment.name!r} are still queued or running. "
                    "Remove it once they finish, or cancel them first."
                ),
                details={"environment_id": str(environment.id), "eval_runs": evals},
            )
        name = environment.name
        await artifact_repo.detach_environment(self.db, environment_id=environment.id)
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

    async def _checked_connections(
        self, ctx: AuthContext, entries: Sequence[EnvironmentConnectionWrite]
    ) -> list[AgentEnvironmentConnection]:
        """The overrides as rows, once each one names things this caller may lend.

        Both sides must be the organization's own: an MCP override pairs two
        organization connections - never a member's personal one, for the reason
        publish refuses one - and a secret override pairs two vault secrets of
        one kind and purpose, the test one readable by the caller, because an
        environment runs it for everybody who reaches the environment. Misses
        and refusals read alike, as they do at publish, so the vault cannot be
        enumerated one guessed id at a time.

        A null test side is an override too: the binding is off here, which an
        operator can ask for directly and is what a deleted test side becomes.
        The production side of a switched-off MCP binding is still checked, so
        an override cannot name what the organization does not hold.

        Raises:
            BadRequestError: On a duplicate override, an override onto itself, or
                a side the organization does not have or the caller cannot lend.
        """
        seen: set[tuple[str, UUID]] = set()
        for entry in entries:
            if (entry.kind, entry.production_id) in seen:
                raise BadRequestError(
                    message="A binding can have one test replacement per environment",
                    details={"kind": entry.kind, "production_id": entry.production_id},
                )
            seen.add((entry.kind, entry.production_id))
            if entry.production_id == entry.test_id:
                raise BadRequestError(
                    message="A test replacement must be a different connection or secret",
                    details={"kind": entry.kind, "production_id": entry.production_id},
                )

        mcp = [entry for entry in entries if entry.kind == ConnectionKind.MCP]
        found = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db,
            connection_ids=[
                *(entry.production_id for entry in mcp),
                *(entry.test_id for entry in mcp if entry.test_id is not None),
            ],
            organization_id=ctx.organization_id,
        )
        for entry in mcp:
            for connection_id in (entry.production_id, entry.test_id):
                if connection_id is not None and connection_id not in found:
                    raise BadRequestError(
                        message=(
                            f"MCP server {connection_id} is not shared with this organization. "
                            "Both sides of an override must be organization connections."
                        ),
                        details={"connection_id": connection_id},
                    )

        for entry in entries:
            if entry.kind == ConnectionKind.SECRET and entry.test_id is not None:
                await self._check_secret_pair(ctx, entry, entry.test_id)

        return [
            AgentEnvironmentConnection(
                kind=entry.kind,
                production_id=entry.production_id,
                test_connection_id=entry.test_id if entry.kind == ConnectionKind.MCP else None,
                test_secret_id=entry.test_id if entry.kind == ConnectionKind.SECRET else None,
            )
            for entry in entries
        ]

    async def _check_secret_pair(
        self, ctx: AuthContext, entry: EnvironmentConnectionWrite, test_id: UUID
    ) -> None:
        """Refuse a test secret that could not stand in for the production one."""
        production = await organization_secret_repo.get(
            self.db, entry.production_id, organization_id=ctx.organization_id
        )
        test = await organization_secret_repo.get(
            self.db, test_id, organization_id=ctx.organization_id
        )
        if (
            production is None
            or test is None
            or not await resolve_access(self.db, ctx, test, Perm.SECRETS_VIEW, resource_type=SECRET)
        ):
            raise BadRequestError(
                message="That key is not in this organization's vault",
                details={"production_id": entry.production_id, "test_id": entry.test_id},
            )
        if (test.kind, test.purpose) != (production.kind, production.purpose):
            raise BadRequestError(
                message=(
                    "That key cannot stand in for the one the agent binds: a test key must "
                    "be the same kind of key, for the same service"
                ),
                details={"production_id": entry.production_id, "test_id": entry.test_id},
            )

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
        version_ids = {environment.version_id for environment in environments}
        found = await agent_repo.get_versions_by_ids(
            self.db, list(version_ids), organization_id=ctx.organization_id
        )
        return {
            version_id: (found[version_id].version if version_id in found else 0)
            for version_id in version_ids
        }
