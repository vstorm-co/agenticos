"""Agent registry service - create, edit, publish, roll back.

The lifecycle this enforces is the whole reason agents are two tables:

    edit draft -> validate -> publish (freeze a version) -> run that version

Validation happens at publish, never at run time. An agent that references a
deleted collection or an ungranted scope is refused while someone is looking at
a form and can fix it, rather than at 3am in a customer conversation.

Rolling back publishes a *new* version copied from an old one. The alternative -
moving a pointer backwards - would make run history lie about what was live.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections import Counter
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import TOOL_NAME_PATTERN, CapabilityDef
from app.agents.capabilities import get as get_capability
from app.agents.default_instructions import DEFAULT_INSTRUCTIONS
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    credential_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    member_repo,
    organization_secret_repo,
    resource_grant_repo,
    sandbox_connection_repo,
)
from app.schemas.agent import AgentRead, AgentVersionRead
from app.services.access import AGENT, COLLECTION, SECRET, resolve_access, visible_resource_ids
from app.services.file_storage import IMAGE_MIME_TYPES, MAX_AVATAR_SIZE, get_file_storage
from app.services.sandbox_workspace import sandbox_config

logger = logging.getLogger(__name__)

_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]+")
_SLUG_TRIM = re.compile(r"-{2,}")

# Scopes an organization grants by default. Real per-org scope management is a
# later concern; hardcoding the safe set here keeps the check honest in the
# meantime rather than disabling it and forgetting.
DEFAULT_GRANTED_SCOPES = frozenset(
    {"knowledge:read", "web:read", "code:execute", "sandbox:execute"}
)

# How far the clone naming loop counts before it lets the collision be reported.
_MAX_COPIES = 50
# `AgentSpec.name` is bounded, and a copy of a copy grows. Truncating the base
# rather than the suffix keeps "(copy 3)" readable - it is the part that says
# which one this is.
_NAME_LIMIT = 128


def _copy_name(base: str, attempt: int) -> str:
    """What the nth copy of `base` is called."""
    suffix = " (copy)" if attempt == 1 else f" (copy {attempt})"
    return f"{base[: _NAME_LIMIT - len(suffix)].rstrip()}{suffix}"


async def _sandbox_problems(db: AsyncSession, ctx: AuthContext, spec: AgentSpec) -> list[str]:
    """Workspace configurations this organization cannot honour.

    Every one of these fails at run time otherwise, and by then the author is not
    looking at a form - they are looking at a conversation where an agent stopped
    answering. Each is also something the spec cannot know on its own: which
    hosts this organization has registered, and what a backend without containers
    does with a container's runtime.

    What is deliberately *not* refused here is `session_scope="user"` on an agent
    that might be reached without one. Publishing cannot know which surfaces an
    agent will be exposed to, and a web-only agent with a per-user workspace is a
    perfectly good configuration - as is one whose Slack binding overrides the
    scope to `channel`. The run refuses instead, by name, when it turns out there
    is nobody to attribute the workspace to.
    """
    config = sandbox_config(spec)
    if config is None:
        return []

    problems: list[str] = []
    if config.backend == "state":
        if config.runtime is not None:
            problems.append(
                "The 'state' workspace runs no container, so it has no runtime to "
                "choose. Clear the runtime, or put this agent on a sandbox connection."
            )
        if config.connection_id is not None:
            problems.append(
                "The 'state' workspace is stored by the platform, so it does not run "
                "on a sandbox connection. Clear the connection, or switch the backend."
            )
        return problems

    connection = None
    if config.connection_id is not None:
        connection = await sandbox_connection_repo.get(
            db, config.connection_id, organization_id=ctx.organization_id
        )
        if connection is None:
            problems.append(
                "The sandbox connection this agent names does not exist in this "
                "organization. Pick one that does, or leave it unset to use the default."
            )
    else:
        connection = await sandbox_connection_repo.get_default(
            db, organization_id=ctx.organization_id
        )
        if connection is None:
            problems.append(
                "This organization has registered no sandbox connection, so an agent "
                "cannot be given a container-backed workspace. Register one, or use "
                "the 'state' workspace, which needs nothing."
            )

    if connection is not None and connection.secret_id is None:
        problems.append(
            f"The sandbox connection '{connection.name}' has no credential, so no "
            "sandbox can be opened on it. Attach its key in the vault."
        )
    return problems


def _tool_override_problems(binding: CapabilityBindingSpec, definition: CapabilityDef) -> list[str]:
    """Everything wrong with how a binding renames its capability's tools.

    All three failures are silent at run time if they are not caught here. An
    override keyed on a tool that does not exist changes nothing and says
    nothing. A name the model cannot emit is a tool it can never call. And two
    tools sharing a name is a `UserError` from deep inside the toolset, raised
    mid-conversation rather than while somebody is looking at a form.
    """
    problems: list[str] = []

    unknown = sorted(set(binding.tool_overrides) - definition.tool_ids)
    if unknown:
        problems.append(
            f"Capability '{binding.id}' has no tool named {', '.join(unknown)} to rename"
        )

    uncallable = sorted(
        override.name
        for override in binding.tool_overrides.values()
        if override.name is not None and not TOOL_NAME_PATTERN.fullmatch(override.name)
    )
    if uncallable:
        problems.append(
            f"Capability '{binding.id}' renames a tool to "
            f"{', '.join(repr(name) for name in uncallable)}, which a model cannot call: "
            "use letters, digits, underscores and dashes"
        )

    counts = Counter(tool.name for tool in definition.effective_tools(binding.tool_overrides))
    clashing = sorted(name for name, count in counts.items() if count > 1)
    if clashing:
        problems.append(
            f"Capability '{binding.id}' would offer two tools called {', '.join(clashing)}"
        )

    return problems


def slugify(name: str) -> str:
    """A URL- and mention-safe handle derived from a name.

    Used in agent URLs and as the `@handle` on chat platforms, so it must stay
    stable and unambiguous - which is why it is generated once at creation and
    then owned by the row, not recomputed when the name changes.
    """
    slug = _SLUG_ALLOWED.sub("-", name.strip().lower())
    slug = _SLUG_TRIM.sub("-", slug).strip("-")
    return slug[:64] or "agent"


class AgentRegistryService:
    """Manage an organization's agents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- reading --------------------------------------------------------

    async def get(
        self, ctx: AuthContext, agent_id: UUID, *, perm: Perm = Perm.AGENTS_VIEW
    ) -> Agent:
        """Fetch an agent the caller may reach, or report it as missing.

        A permission failure is reported as "not found" so agent ids cannot be
        probed by someone who merely belongs to the organization.
        """
        agent = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
        if agent is None:
            raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
        allowed = await resolve_access(self.db, ctx, agent, perm, resource_type=AGENT)
        if not allowed:
            raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
        return agent

    async def list_agents(
        self,
        ctx: AuthContext,
        *,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentRead], int]:
        """Agents visible to the caller under their role scope and grants."""
        # `None` is `visible_resource_ids` saying the role already reaches every
        # agent, which is exactly what `see_all` tells the query - so both come
        # from the one call rather than from the scope being read twice and the
        # two answers being trusted to agree.
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW
        )
        agents, total = await agent_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
            include_archived=include_archived,
            skip=skip,
            limit=limit,
        )
        # How far each agent reaches, one grouped query per question rather than
        # one per row: the gallery card says "shared with 3" and "on Slack", and
        # twenty cards must not mean forty queries.
        agent_ids = [agent.id for agent in agents]
        shared_counts = await resource_grant_repo.count_for_resources(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=AGENT.key,
            resource_ids=agent_ids,
        )
        surfaces = await agent_exposure_repo.active_surfaces_for_agents(
            self.db, organization_id=ctx.organization_id, agent_ids=agent_ids
        )
        rows = [
            AgentRead(
                id=agent.id,
                slug=agent.slug,
                name=agent.name,
                description=agent.description,
                status=agent.status,
                visibility=agent.visibility,
                owner_user_id=agent.owner_user_id,
                current_version_id=agent.current_version_id,
                has_avatar=agent.has_avatar,
                shared_user_count=shared_counts.get(agent.id, 0),
                channels=surfaces.get(agent.id, []),
                created_at=agent.created_at,
                updated_at=agent.updated_at,
            )
            for agent in agents
        ]
        return rows, total

    # -- writing --------------------------------------------------------

    async def create(self, ctx: AuthContext, spec: AgentSpec) -> Agent:
        """Create an agent in draft.

        Raises:
            AlreadyExistsError: If the derived slug is taken. Slugs are how agents are
                mentioned in Slack, so silently disambiguating one would route
                messages to the wrong agent.
        """
        # A new agent opens with a prompt rather than an empty box. An agent with
        # no instructions still answers - as whatever the underlying model is by
        # default, which is a different product on every provider and changes when
        # the model is upgraded. Applied here rather than as a field default,
        # because a spec imported with an empty prompt means an empty prompt.
        if not spec.instructions.strip():
            spec = spec.model_copy(update={"instructions": DEFAULT_INSTRUCTIONS})

        slug = slugify(spec.name)
        if await agent_repo.get_by_slug(self.db, slug, organization_id=ctx.organization_id):
            raise AlreadyExistsError(
                message=(
                    f"The handle @{slug} is already taken. It is derived from the name and "
                    "is what an @mention resolves to, so it has to be unique and cannot be "
                    "changed later - give this agent a name that produces a different handle."
                ),
                # `field` names the input a person is looking at, which is not
                # what the server calls it: they typed a *name*, and the thing
                # that collided is the handle derived from it. Without this the
                # form has to guess where to put the message.
                details={"slug": slug, "field": "name"},
            )

        agent = await agent_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            slug=slug,
            name=spec.name,
            description=spec.description,
            draft_spec=spec.model_dump(mode="json"),
            owner_user_id=ctx.user_id,
            created_by_user_id=ctx.user_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.created",
            target_type="agent",
            target_id=str(agent.id),
            details={"slug": slug, "name": spec.name},
        )
        return agent

    async def clone(self, ctx: AuthContext, agent_id: UUID, *, name: str | None = None) -> Agent:
        """Copy an agent's draft into a new agent, in draft.

        What is copied is the draft spec and nothing else. The copy starts with
        no versions, no grants and no exposures, owned by whoever cloned it -
        because every one of those is a statement about *that* agent that nobody
        has made about this one. Inheriting the shares alone would hand a copy
        to an audience who never saw it published.

        Cloning creates, so it needs the role that may create. A grant on the
        source widens what its holder may do *to the source*; it has never meant
        they may add agents to the organization, and reading this as edit-on-a-row
        would let a Viewer with one shared agent fill the registry.

        Raises:
            AuthorizationError: If the caller's role may not create agents.
            AlreadyExistsError: If the derived handle is taken.
        """
        source = await self.get(ctx, agent_id)
        if not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(
                message="Cloning an agent creates one, which your role does not allow"
            )

        spec = AgentSpec.model_validate(
            {**source.draft_spec, "name": name or await self._free_copy_name(ctx, source.name)}
        )
        clone = await self.create(ctx, spec)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.cloned",
            target_type="agent",
            target_id=str(clone.id),
            details={"source_agent_id": str(source.id), "source_slug": source.slug},
        )
        return clone

    async def _free_copy_name(self, ctx: AuthContext, base: str) -> str:
        """A "(copy)" name whose handle nobody has taken yet.

        Cloning twice is ordinary, and the second one has no name field to
        correct - the name is derived, so refusing it with "pick another name"
        would be asking for something the caller was never offered. Numbering
        stops at :data:`_MAX_COPIES`, after which `create` raises and says the
        handle is taken, which by then is the honest answer.
        """
        for attempt in range(1, _MAX_COPIES + 1):
            candidate = _copy_name(base, attempt)
            taken = await agent_repo.get_by_slug(
                self.db, slugify(candidate), organization_id=ctx.organization_id
            )
            if taken is None:
                return candidate
        return _copy_name(base, _MAX_COPIES)

    async def save_draft(self, ctx: AuthContext, agent_id: UUID, spec: AgentSpec) -> Agent:
        """Store an edited spec without making it live.

        Deliberately does not validate references: half-finished configuration
        must be saveable, or the Builder becomes a form you cannot leave.
        Validation is publish's job.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        return await agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "draft_spec": spec.model_dump(mode="json"),
                "name": spec.name,
                "description": spec.description,
            },
        )

    async def validate_spec(self, ctx: AuthContext, spec: AgentSpec) -> None:
        """Check every reference a spec makes, and report all problems at once.

        Reporting all of them matters: fixing a form one error per round trip is
        the difference between a Builder people use and one they avoid.

        Raises:
            BadRequestError: With a `problems` list naming each broken
                reference.
        """
        problems: list[str] = []

        for binding in spec.capabilities:
            try:
                definition = get_capability(binding.id)
            except BadRequestError:
                problems.append(f"Unknown capability: {binding.id}")
                continue
            missing_scopes = definition.scopes - DEFAULT_GRANTED_SCOPES
            if missing_scopes:
                problems.append(
                    f"Capability '{binding.id}' needs scopes not granted here: "
                    f"{', '.join(sorted(missing_scopes))}"
                )
            try:
                definition.validate_config(binding.config)
            except BadRequestError as exc:
                problems.append(f"Capability '{binding.id}': {exc.message}")
            # A tool_approval key that matches nothing is the dangerous kind of
            # typo: it is not an error at run time, it is silence - the tool the
            # author meant to gate runs unapproved and nobody is told.
            unknown_tools = sorted(set(binding.tool_approval) - definition.tool_ids)
            if unknown_tools:
                problems.append(
                    f"Capability '{binding.id}' has no tool named "
                    f"{', '.join(unknown_tools)} to set approval for"
                )
            problems.extend(_tool_override_problems(binding, definition))
            problems.extend(await self._secret_problems(ctx, binding, definition))

        # A model, named. There is no organization-wide default to fall back
        # on: a model an agent did not choose is one somebody else's change can
        # swap underneath it, and "why did this get more expensive" then has no
        # answer in the agent's own history.
        if spec.model_profile_id is None:
            problems.append("No model selected - pick one before publishing")
        else:
            profile = await credential_repo.get_profile(
                self.db, spec.model_profile_id, organization_id=ctx.organization_id
            )
            if profile is None:
                problems.append("The selected model profile no longer exists")

        for collection_id in spec.collection_ids:
            collection = await knowledge_base_repo.get_by_id(self.db, collection_id)
            # An agent searches its bound collections for everyone who can run
            # it, so binding one shares what is in it - the publisher has to be
            # able to reach it themselves. "Not found" covers both that and a
            # missing id on purpose: a refusal that reads differently would map
            # the organization's private collections one guess at a time.
            reachable = collection is not None and await resolve_access(
                self.db, ctx, collection, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )
            if not reachable:
                problems.append(f"Collection not found: {collection_id}")

        for connection_id in spec.mcp_server_ids:
            connection = await mcp_connection_repo.get_org_scoped_by_id(
                self.db, connection_id=connection_id, organization_id=ctx.organization_id
            )
            if connection is None:
                # Says which of the two ways it can fail applies, because the
                # likely one - a personal connection picked in the Builder - is
                # not a missing row and "not found" would send the person
                # looking for something that is right in front of them.
                problems.append(
                    f"MCP server {connection_id} is not shared with this organization. "
                    "A published agent can only use connections the organization owns, "
                    "never a member's personal one - otherwise what it can reach would "
                    "depend on who happens to run it."
                )

        problems.extend(await _sandbox_problems(self.db, ctx, spec))

        if problems:
            raise BadRequestError(
                message="This agent cannot be published yet",
                details={"problems": problems},
            )

    async def _secret_problems(
        self,
        ctx: AuthContext,
        binding: CapabilityBindingSpec,
        definition: CapabilityDef,
    ) -> list[str]:
        """Everything wrong with the secret a binding points at.

        Four ways to get this wrong and each one fails at run time otherwise,
        somewhere far from the form: no reference where the capability needs
        one, a reference to a secret that is gone or belongs to another
        organization, a secret of the wrong shape, and a reference where nothing
        consumes it - which reads as configured but does nothing, and is the
        only one of the four a person would never notice.
        """
        requirement = definition.secret
        if requirement is None:
            if binding.secret_id is not None:
                return [
                    f"Capability '{binding.id}' does not use a secret, so the one selected "
                    "here would be stored and never read"
                ]
            return []
        # Whether *this configuration* authenticates. Web search takes a key for
        # Tavily and none for DuckDuckGo, and the same predicate answers here and
        # at build time - two answers would mean an agent that publishes and then
        # refuses to run.
        try:
            config = definition.validate_config(binding.config)
        except BadRequestError:
            # Already reported by the caller as a config problem; nothing here
            # can be said about a secret for a configuration that does not parse.
            return []
        if not definition.needs_secret(config) and binding.secret_id is None:
            return []
        if binding.secret_id is None:
            return [
                f"Capability '{binding.id}' needs a {requirement.kind.value} secret "
                f"({requirement.description}) and none is selected"
            ]
        secret = await organization_secret_repo.get(
            self.db, binding.secret_id, organization_id=ctx.organization_id
        )
        if secret is None:
            return [
                f"Capability '{binding.id}' points at a secret this organization does not "
                f"have: {binding.secret_id}"
            ]
        # An agent runs its bindings for everyone who can run the agent, so
        # binding a key is lending it. Whoever does the lending has to be able to
        # reach the key themselves - the picker only ever offers what they can
        # see, but the API took an id, and an id is guessable in a way a list is
        # not. Phrased as "does not have" for the same reason `_get` answers 404:
        # a refusal that differs from a miss is a way to enumerate the vault.
        if not await resolve_access(self.db, ctx, secret, Perm.SECRETS_VIEW, resource_type=SECRET):
            return [
                f"Capability '{binding.id}' points at a secret this organization does not "
                f"have: {binding.secret_id}"
            ]
        if secret.kind != requirement.kind.value:
            return [
                f"Capability '{binding.id}' needs a {requirement.kind.value} secret, but "
                f"'{secret.name}' holds a {secret.kind}"
            ]
        return []

    async def publish(
        self, ctx: AuthContext, agent_id: UUID, *, note: str | None = None
    ) -> AgentVersion:
        """Validate the draft and freeze it as the version that runs."""
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        spec = AgentSpec.model_validate(agent.draft_spec)
        await self.validate_spec(ctx, spec)

        number = await agent_repo.next_version_number(self.db, agent_id=agent.id)
        version = await agent_repo.create_version(
            self.db,
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=number,
            spec=spec.model_dump(mode="json"),
            note=note,
            published_by_user_id=ctx.user_id,
        )
        await agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "current_version_id": version.id,
                "status": AgentStatus.PUBLISHED.value,
            },
        )
        await self._repoint_default_environment(ctx, agent=agent, version=version)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.published",
            target_type="agent",
            target_id=str(agent.id),
            details={"version": number, "note": note},
        )
        await self._audit_shared_workspace(ctx, agent=agent, spec=spec, version=number)
        return version

    async def _audit_shared_workspace(
        self, ctx: AuthContext, *, agent: Agent, spec: AgentSpec, version: int
    ) -> None:
        """Record that this agent's workspace is now shared between people.

        `session_scope="agent"` means any user of the agent reads what another
        user wrote. It ships without a permission of its own, so the audit entry
        is what makes the decision answerable afterwards: a member who opens a
        chat and finds a file they never created can be told when the sharing
        started and who chose it, instead of being left to conclude that
        something leaked.
        """
        config = sandbox_config(spec)
        if config is None or config.session_scope != "agent":
            return
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.workspace_shared",
            target_type="agent",
            target_id=str(agent.id),
            details={
                "version": version,
                "session_scope": config.session_scope,
                "backend": config.backend,
            },
        )

    async def _repoint_default_environment(
        self, ctx: AuthContext, *, agent: Agent, version: AgentVersion
    ) -> None:
        """Keep the default environment on the version that was just published.

        Publish moves exactly one pointer: the default. Named environments
        somebody pinned - dev on v12, a client's env held back on v9 - stay
        where they were put; promotion is `AgentEnvironmentService.update`,
        on purpose and audited. An agent published for the first time gets its
        `production` default here, so every published agent has one without a
        backfill ever being anyone's job again.
        """
        default = await agent_environment_repo.get_default_for_agent(self.db, agent_id=agent.id)
        if default is None:
            await agent_environment_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="production",
                version_id=version.id,
                is_default=True,
                created_by_user_id=ctx.user_id,
            )
            return
        await agent_environment_repo.update(
            self.db, environment=default, update_data={"version_id": version.id}
        )

    async def rollback(
        self, ctx: AuthContext, agent_id: UUID, *, to_version_id: UUID
    ) -> AgentVersion:
        """Republish an earlier spec as a new version.

        History stays linear: the timeline shows that a rollback happened rather
        than pretending the bad version never existed.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        source = await agent_repo.get_version(
            self.db, to_version_id, organization_id=ctx.organization_id
        )
        if source is None or source.agent_id != agent.id:
            raise NotFoundError(
                message="Version not found", details={"version_id": str(to_version_id)}
            )

        spec = AgentSpec.model_validate(source.spec)
        await self.validate_spec(ctx, spec)

        number = await agent_repo.next_version_number(self.db, agent_id=agent.id)
        version = await agent_repo.create_version(
            self.db,
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=number,
            spec=source.spec,
            note=f"Rollback to v{source.version}",
            published_by_user_id=ctx.user_id,
        )
        await agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "current_version_id": version.id,
                "status": AgentStatus.PUBLISHED.value,
                "draft_spec": source.spec,
            },
        )
        await self._repoint_default_environment(ctx, agent=agent, version=version)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.rolled_back",
            target_type="agent",
            target_id=str(agent.id),
            details={"from_version": source.version, "new_version": number},
        )
        return version

    async def archive(self, ctx: AuthContext, agent_id: UUID) -> Agent:
        """Retire an agent, keeping its history and its runs.

        What people mean by "delete an agent" is almost always this: stop it,
        keep the trail. Real deletion is a separate, deliberate act.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        updated = await agent_repo.update(
            self.db, agent=agent, update_data={"status": AgentStatus.ARCHIVED.value}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.archived",
            target_type="agent",
            target_id=str(agent.id),
        )
        return updated

    async def unarchive(self, ctx: AuthContext, agent_id: UUID) -> Agent:
        """Bring a retired agent back.

        It returns to what it was, which is decided by whether it has a version
        to run - not by remembering the status it had. Reviving something as
        published when its version was since deleted would be claiming it can
        run, and the run would be the thing that found out.

        Raises:
            BadRequestError: If the agent is not archived. Silently succeeding
                would make "restore" look like it did something.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        if agent.status != AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is not archived",
                details={"agent_id": str(agent.id), "status": agent.status},
            )
        restored = (
            AgentStatus.PUBLISHED.value
            if agent.current_version_id is not None
            else AgentStatus.DRAFT.value
        )
        updated = await agent_repo.update(self.db, agent=agent, update_data={"status": restored})
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.unarchived",
            target_type="agent",
            target_id=str(agent.id),
            details={"status": restored},
        )
        return updated

    async def set_avatar(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        file_data: bytes,
        filename: str,
        content_type: str | None,
    ) -> Agent:
        """Replace an agent's picture.

        Raises:
            BadRequestError: If the file is not an image this platform accepts,
                or is over the size limit.
        """
        if content_type not in IMAGE_MIME_TYPES:
            raise BadRequestError(message="Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > MAX_AVATAR_SIZE:
            raise BadRequestError(message="Avatar image too large. Maximum 2MB.")

        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        storage = get_file_storage()
        if agent.avatar_url:
            # A replaced picture is not worth failing an upload over, and the
            # old file is unreachable the moment the row stops pointing at it.
            with contextlib.suppress(Exception):
                await storage.delete(agent.avatar_url)
        path = await storage.save(f"avatars/agents/{agent.id}", filename, file_data)
        return await agent_repo.update(self.db, agent=agent, update_data={"avatar_url": path})

    async def avatar_path(self, ctx: AuthContext, agent_id: UUID) -> str:
        """Where the agent's picture is on disk, for the route that streams it.

        Reading the picture goes through the same access check as reading the
        agent: an avatar is not public just because it is an image, and an
        unguarded path would say which agent ids exist.

        Raises:
            NotFoundError: If the agent has no avatar, or the stored file is
                gone - indistinguishable to a caller, and deliberately so.
        """
        agent = await self.get(ctx, agent_id)
        path = get_file_storage().get_full_path(agent.avatar_url) if agent.avatar_url else None
        if path is None or not path.exists():
            raise NotFoundError(
                message="This agent has no avatar", details={"agent_id": str(agent_id)}
            )
        return str(path)

    async def delete(self, ctx: AuthContext, agent_id: UUID) -> None:
        """Permanently remove an agent, its versions and its shares."""
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        # The grant table is generic and has no foreign key to the agent, so
        # nothing cascades on its behalf.
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=AGENT.key,
            resource_id=agent.id,
        )
        await agent_repo.delete(self.db, agent)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.deleted",
            target_type="agent",
            target_id=str(agent_id),
        )

    async def get_version(self, ctx: AuthContext, agent_id: UUID, version_id: UUID) -> AgentVersion:
        """One published version of one agent.

        Checked against the agent rather than the version alone: a version id is
        reachable only through the agent that owns it, so an agent somebody may
        not see does not leak its history through a second endpoint.

        Raises:
            NotFoundError: If the version does not exist or belongs to another
                agent - indistinguishable, deliberately.
        """
        agent = await self.get(ctx, agent_id)
        version = await agent_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        if version is None or version.agent_id != agent.id:
            raise NotFoundError(
                message="Version not found", details={"version_id": str(version_id)}
            )
        return version

    async def list_versions(self, ctx: AuthContext, agent_id: UUID) -> list[AgentVersionRead]:
        """The timeline, with who published each entry.

        Resolved here rather than left as ids: "who changed this" is the whole
        reason a history is read, and a column of uuids answers it with another
        question. One lookup for the page, not one per row.
        """
        agent = await self.get(ctx, agent_id)
        versions = await agent_repo.list_versions(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id
        )
        emails = await member_repo.get_emails_for_users(
            self.db,
            organization_id=ctx.organization_id,
            user_ids=[v.published_by_user_id for v in versions if v.published_by_user_id],
        )
        return [
            AgentVersionRead(
                id=version.id,
                version=version.version,
                note=version.note,
                published_by_user_id=version.published_by_user_id,
                published_by_email=emails.get(version.published_by_user_id)
                if version.published_by_user_id
                else None,
                created_at=version.created_at,
            )
            for version in versions
        ]

    async def get_runnable_spec(
        self, ctx: AuthContext, agent_id: UUID, *, environment_id: UUID | None = None
    ) -> tuple[Agent, AgentSpec, UUID]:
        """The published spec for a run, and the version id it was resolved to.

        Which version answers is the environment's decision: an explicit
        `environment_id` (a dev bot, an env-pinned surface) resolves to the
        version that environment pins; nothing named resolves to
        `current_version_id`, which publish keeps in sync with the default
        environment. The resolved id is returned so the run row records the
        version that actually answered, not the default of the moment.

        Raises:
            BadRequestError: If the agent has never been published or is
                archived - running a draft would mean running something nobody
                approved.
            NotFoundError: If the named environment is not this agent's.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        if agent.status == AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is archived", details={"agent_id": str(agent.id)}
            )
        if agent.current_version_id is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' has not been published yet",
                details={"agent_id": str(agent.id)},
            )

        version_id = agent.current_version_id
        if environment_id is not None:
            environment = await agent_environment_repo.get(
                self.db, environment_id, organization_id=ctx.organization_id
            )
            if environment is None or environment.agent_id != agent.id:
                raise NotFoundError(
                    message="Environment not found",
                    details={"environment_id": str(environment_id)},
                )
            version_id = environment.version_id

        version = await agent_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id
        )
        if version is None:
            raise BadRequestError(
                message=f"Agent '{agent.name}' points at a missing version",
                details={"agent_id": str(agent.id)},
            )
        return agent, AgentSpec.model_validate(version.spec), version.id
