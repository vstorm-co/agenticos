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
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import TOOL_NAME_PATTERN, CapabilityDef
from app.agents.capabilities import get as get_capability
from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.default_instructions import DEFAULT_INSTRUCTIONS
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec, SubagentRef
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
    skill_repo,
)
from app.schemas.agent import AgentRead, AgentVersionRead
from app.services.access import (
    AGENT,
    COLLECTION,
    SECRET,
    SKILL,
    resolve_access,
    visible_resource_ids,
)
from app.services.file_storage import IMAGE_MIME_TYPES, MAX_AVATAR_SIZE, get_file_storage
from app.services.sandbox_workspace import sandbox_config

logger = logging.getLogger(__name__)

_SLUG_ALLOWED = re.compile(r"[^a-z0-9-]+")
_SLUG_TRIM = re.compile(r"-{2,}")

# Scopes an organization grants by default. Real per-org scope management is a
# later concern; hardcoding the safe set here keeps the check honest in the
# meantime rather than disabling it and forgetting.
#
# `agents:delegate` is granted like the rest, because it is not the gate on who
# may be delegated to - that is `agents:run`, checked per delegate below, on the
# publisher, against the row. What the scope answers is a different question a
# permission cannot: whether this *deployment* allows agents to call agents at
# all. Removing it here turns delegation off everywhere in one edit, which is
# what an operator who does not want fan-out billing or nested runs needs, and
# every spec that delegates then says so at publish instead of at 3am.
DEFAULT_GRANTED_SCOPES = frozenset(
    {"knowledge:read", "web:read", "code:execute", "sandbox:execute", "agents:delegate"}
)

# The registry id of the delegation capability. Held here rather than imported
# for the same reason `SANDBOX_CAPABILITY_ID` is: publish validation reads a
# binding out of a spec, and an id is part of the spec format.
DELEGATION_CAPABILITY_ID = "subagents"

# How many pinned versions the cycle walk will follow before it stops and says
# so. The visited set already makes the walk terminate on a graph that loops;
# this bounds what it *costs*, because the number of pins is not bounded by the
# spec and publish holds a transaction open while every one of them is read.
_MAX_DELEGATION_NODES = 200

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


@dataclass(frozen=True)
class _PinnedDelegate:
    """A delegate pin that resolved: which agent, which version, and its spec.

    The spec is the frozen one the pin names, so following it is following what a
    published parent will actually call. Its `name` is prose - it names the
    delegate in a refusal a person reads. What the *model* addresses the delegate
    by is the agent row's `slug`, which is not here because the walk below reads
    versions rather than rows.
    """

    agent_id: UUID
    version_id: UUID
    spec: AgentSpec


@dataclass(frozen=True)
class _ResolvedPins:
    """What the pin check found, for the three callers that each need one part."""

    delegates: list[_PinnedDelegate]
    """The pins that resolved, for the cycle walk to follow."""
    handles: list[str]
    """Each resolved delegate's `Agent.slug` - what the model addresses it by."""
    problems: list[str]


@dataclass(frozen=True)
class _DelegationStep:
    """One delegate the cycle walk has reached, and how it got there."""

    delegate: _PinnedDelegate
    chain: tuple[str, ...]
    """The names from the agent being published down to this delegate's caller."""
    ancestors: frozenset[UUID]
    """Which agents are already in that chain - reaching one again is the cycle."""


def delegation_binding(spec: AgentSpec) -> CapabilityBindingSpec | None:
    """This agent's delegation binding, if it has one that is switched on.

    Read out of the spec rather than passed in, the same way `sandbox_config` is,
    so publish validation and the runtime find the specialists, the depth cap and
    the shared capabilities in one place instead of two that agree until they do
    not.

    A *disabled* binding is not delegation: the capability is not built, so
    nothing reads the pins or the specialists it carries - and treating it as
    enabled here would refuse a spec over a specialist that can never run.
    """
    for binding in spec.capabilities:
        if binding.id == DELEGATION_CAPABILITY_ID and binding.enabled:
            return binding
    return None


def _share_problems(spec: AgentSpec, config: SubagentsConfig) -> list[str]:
    """Everything wrong with what this agent shares with its delegates.

    A delegate runs on its own spec plus whatever the parent explicitly hands
    it, so this list is the parent lending what it holds. Naming a capability it
    is not bound to lends nothing - it is a line of configuration that reads as
    a decision and does nothing, which is the failure mode nobody notices. A
    binding that is switched off is not held either: the parent does not build
    it, so there is nothing for the delegate to receive.

    Delegation itself is refused, and it is the one id an "is it held" check
    could never catch: an agent that shares anything holds the delegation
    binding by definition. Sharing it copies the parent's binding onto a
    delegate that binds none, and every field the runtime then reads comes from
    the *parent* - its inline specialists, its `allow_dynamic`, its `max_fanout`
    and `max_depth`, and this share list again one level down. That is a
    delegate answering with a policy its own author never wrote and no reviewer
    of its spec can see. Whether a delegate may delegate is its own spec's
    answer, bounded by the parent's `max_depth`.
    """
    problems: list[str] = []
    held = {binding.id for binding in spec.capabilities if binding.enabled}
    unbound = sorted(set(config.share_with_delegates) - held)
    if unbound:
        problems.append(
            "Delegation shares capabilities this agent is not bound to: "
            f"{', '.join(unbound)}. Bind them here first, or drop them from the list."
        )
    if DELEGATION_CAPABILITY_ID in config.share_with_delegates:
        problems.append(
            f"Delegation cannot share '{DELEGATION_CAPABILITY_ID}' with its delegates: a "
            "delegate would inherit this agent's specialists, its depth and fan-out "
            "caps and this list, none of which its own author wrote. Whether a delegate "
            "may delegate is a question its own spec answers."
        )
    return problems


def _collision_problems(names: Sequence[str]) -> list[str]:
    """Delegates the parent's model cannot tell apart.

    A delegate is addressed by one name, so two of them sharing it leaves the
    model no way to say which it meant and the second silently shadows the first.
    :class:`AgentSpec` already refuses the same agent pinned twice; this is the
    other half, where two *different* delegates are called the same thing.

    A published delegate arrives here as its agent row's `slug` - the handle
    :func:`slugify` generates once at creation and the row then owns. Never as
    something re-derived from a spec name: `save_draft` updates the name and not
    the slug, so the two disagree the moment an agent is renamed, and only one of
    them is what the delegation is wired to. It also has to be the slug because
    `uq_agent_org_slug` is what makes handles unique inside an organization -
    comparing derived names would both refuse collisions the database would never
    have permitted and pass real ones whose names happen to reduce alike.

    Which means two *published* delegates cannot collide at all; the constraint
    has already refused that. What can, and what this check is really for, is an
    inline specialist - whose `name` is unconstrained - taking a delegate's
    handle or another specialist's.
    """
    counts = Counter(names)
    clashing = sorted(name for name, count in counts.items() if count > 1)
    if not clashing:
        return []
    return [
        f"More than one delegate is called {', '.join(repr(name) for name in clashing)}, "
        "so the model has no way to say which it means"
    ]


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
        shared_with_me: bool = False,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentRead], int]:
        """Agents visible to the caller under their role scope and grants.

        `shared_with_me` narrows to what was deliberately shared with them -
        org-visible or explicitly granted, and not their own.
        """
        # `None` is `visible_resource_ids` saying the role already reaches every
        # agent, which is exactly what `see_all` tells the query - so both come
        # from the one call rather than from the scope being read twice and the
        # two answers being trusted to agree.
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW
        )
        grant_ids = [] if shared is None else shared
        if shared_with_me and shared is None:
            # A role that reaches everything never looks its grants up - but
            # "shared with me" is a question about grants and visibility, not
            # reach, and without them a Builder's answer would degenerate into
            # "the whole organization minus mine".
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=AGENT.key,
            )
        agents, total = await agent_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
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
        budget_caps = await agent_repo.published_budget_caps(
            self.db,
            version_ids=[agent.current_version_id for agent in agents if agent.current_version_id],
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
                budget_monthly_usd=(
                    budget_caps.get(agent.current_version_id) if agent.current_version_id else None
                ),
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

    async def promote_specialist(
        self,
        ctx: AuthContext,
        specialist: SpecialistSpec,
        *,
        fallback_model_profile_id: UUID | None,
    ) -> Agent:
        """Turn a specialist into a draft agent, owned by whoever promoted it.

        The only honest way to keep a specialist. A delegate is published and an
        inline specialist lives in its parent, but a dynamic one - written by a model
        mid-run - is persisted nowhere, deliberately, because keeping a specialist
        means publishing an agent and that is a person's action. Without this the
        workaround is retyping instructions out of a chat log, which produces an
        agent whose provenance nobody can see; this is the exit that keeps
        "nothing is persisted" a design rather than an obstacle.

        It creates a draft and stops there - `SpecialistSpec.to_agent_spec` reaching
        a `create` rather than the `build_agent` a delegation uses. It does not
        publish, does not pin the new agent as a delegate of any parent, and does not
        touch the specialist it came from: each of those is a separate decision the
        author makes next, with the normal validation in front of it.

        Creating needs the role that may create, so the route gates on
        `AGENTS_EDIT` exactly as `create` does - a specialist a model invented inside
        someone else's run does not become the promoter's agent for free, and does
        not become anyone's without that permission. The draft is owned by
        `ctx.user_id`, because `create` is.
        """
        spec = specialist.to_agent_spec(fallback_model_profile_id=fallback_model_profile_id)
        agent = await self.create(ctx, spec)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.promoted_from_specialist",
            target_type="agent",
            target_id=str(agent.id),
            details={"slug": agent.slug, "specialist": specialist.name},
        )
        return agent

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

    async def validate_spec(
        self, ctx: AuthContext, spec: AgentSpec, *, agent_id: UUID | None = None
    ) -> None:
        """Check every reference a spec makes, and report all problems at once.

        Reporting all of them matters: fixing a form one error per round trip is
        the difference between a Builder people use and one they avoid.

        `agent_id` is which agent this spec belongs to, and it is what makes a
        delegation cycle visible: `A -> B -> A` is created by the publish that
        adds the pin, so the walk has to know that the spec in hand is A's - B's
        stored version says nothing about a pin that does not exist yet. All
        three callers pass it - both publish paths and the draft check - so every
        one of them reports a cycle that closes on the agent in hand. Omitted, the
        walk still finds a loop that closes anywhere *below* this agent, because
        that one is visible in the delegates' own stored specs; only a cycle
        through the root goes unseen. That is the whole of what the default costs.

        Args:
            ctx: Who is publishing. Every reference is checked against *their*
                access, not the organization's, so binding a collection or a key
                cannot lend out something the publisher cannot read themselves.
            spec: The spec to check. Its inline specialists are walked with the
                same helpers as the spec itself.
            agent_id: The agent this spec belongs to, when there is one.

        Raises:
            BadRequestError: With a `problems` list naming each broken
                reference.
        """
        problems: list[str] = []

        for binding in spec.capabilities:
            problems.extend(await self._binding_problems(ctx, binding))

        # A model, named. There is no organization-wide default to fall back
        # on: a model an agent did not choose is one somebody else's change can
        # swap underneath it, and "why did this get more expensive" then has no
        # answer in the agent's own history.
        if spec.model_profile_id is None:
            problems.append("No model selected - pick one before publishing")
        else:
            problems.extend(await self._model_profile_problems(ctx, spec.model_profile_id))

        problems.extend(await self._collection_problems(ctx, spec.collection_ids))
        problems.extend(await self._skill_problems(ctx, spec.skill_ids))

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
        problems.extend(await self._delegation_problems(ctx, spec, agent_id=agent_id))

        if problems:
            raise BadRequestError(
                message="This agent cannot be published yet",
                details={"problems": problems},
            )

    async def _binding_problems(
        self, ctx: AuthContext, binding: CapabilityBindingSpec
    ) -> list[str]:
        """Everything wrong with one capability binding.

        One binding rather than a spec's list, because a specialist defined
        inside an agent has bindings too and they are the same bindings - same
        registry, same scopes, same secrets. Two loops that had to be kept in
        step would drift, and the half that drifted would be the one nobody
        thought of as an agent.
        """
        try:
            definition = get_capability(binding.id)
        except BadRequestError:
            return [f"Unknown capability: {binding.id}"]

        problems: list[str] = []
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
        return problems

    async def _model_profile_problems(self, ctx: AuthContext, profile_id: UUID) -> list[str]:
        """Whether a named model profile is still this organization's to run on."""
        profile = await credential_repo.get_profile(
            self.db, profile_id, organization_id=ctx.organization_id
        )
        if profile is None:
            return ["The selected model profile no longer exists"]
        return []

    async def _collection_problems(
        self, ctx: AuthContext, collection_ids: Sequence[UUID]
    ) -> list[str]:
        """Knowledge collections the publisher cannot lend out.

        An agent searches its bound collections for everyone who can run it, so
        binding one shares what is in it - the publisher has to be able to reach
        it themselves. "Not found" covers both that and a missing id on purpose:
        a refusal that reads differently would map the organization's private
        collections one guess at a time.
        """
        problems: list[str] = []
        for collection_id in collection_ids:
            collection = await knowledge_base_repo.get_by_id(self.db, collection_id)
            reachable = collection is not None and await resolve_access(
                self.db, ctx, collection, Perm.COLLECTIONS_VIEW, resource_type=COLLECTION
            )
            if not reachable:
                problems.append(f"Collection not found: {collection_id}")
        return problems

    async def _skill_problems(self, ctx: AuthContext, skill_ids: Sequence[UUID]) -> list[str]:
        """Skills the publisher cannot lend out.

        The same rule as a collection, for the same reason: a bound skill is read
        by every run of the agent, so binding one shares it - its body, and the
        resource files beside it. A skill is written know-how, and a private one
        is private deliberately, so the publisher has to be able to reach it
        themselves. `SKILLS_VIEW` through :func:`resolve_access`, which means an
        explicit grant counts and a member who was shared one skill can bind it
        without being promoted.

        "Not found" covers a missing id, another organization's id, and a row this
        publisher may not read, deliberately indistinguishably: skills are bound
        by UUID from the API and from a hand-edited draft, not only picked from a
        list, so a refusal that read differently would map the organization's
        private skills one guess at a time.

        One query for the whole list rather than one per id, because a run resolves
        them the same way and publish holds a transaction open.
        """
        if not skill_ids:
            return []
        found = await skill_repo.get_many(
            self.db, list(skill_ids), organization_id=ctx.organization_id
        )
        problems: list[str] = []
        for skill_id in skill_ids:
            skill = found.get(skill_id)
            reachable = skill is not None and await resolve_access(
                self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL
            )
            if not reachable:
                problems.append(f"Skill not found: {skill_id}")
        return problems

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

    # -- delegation -----------------------------------------------------

    async def _delegation_problems(
        self, ctx: AuthContext, spec: AgentSpec, *, agent_id: UUID | None
    ) -> list[str]:
        """Everything wrong with what this agent delegates to.

        Three things, checked together because they interact: the specialists
        defined inline, the pins to published agents, and the policy governing
        both. The parent's model addresses a specialist and a delegate the same
        way - by name - so a collision between the two kinds is invisible to
        either half checked alone.

        `max_depth` and `max_fanout` are deliberately absent: they are bounded by
        the config model, and a second check here would be a second place to edit
        when a bound moves - the kind of duplication that ends with the two
        disagreeing and the looser one winning.
        """
        binding = delegation_binding(spec)
        if binding is None:
            if spec.subagents:
                # A pin nothing reads: the capability is what turns these into
                # tools, so without it they are configuration that reads as a
                # decision and has no effect - and the author who wired up three
                # delegates is the last person who would notice.
                return [
                    "This agent names delegates, but its delegation capability is not "
                    "enabled - nothing would ever call them. Enable it, or remove them."
                ]
            return []
        try:
            config = SubagentsConfig.model_validate(binding.config)
        except ValidationError:
            # `_binding_problems` has already reported the configuration itself.
            # A policy that does not parse says nothing further about the
            # specialists it would have carried, and guessing at half of one
            # would report problems against a shape nobody wrote.
            return []

        problems: list[str] = []
        names: list[str] = []
        for specialist in config.inline:
            names.append(specialist.name)
            problems.extend(await self._specialist_problems(ctx, specialist))
        problems.extend(_share_problems(spec, config))

        pins = await self._resolve_pins(ctx, spec.subagents)
        problems.extend(pins.problems)
        # A delegate's handle is its row's slug; a specialist's is the name as
        # typed, which is already constrained to what a tool argument can carry.
        # Both are what the runtime hands the model, which is the only namespace
        # a collision can happen in.
        names.extend(pins.handles)
        problems.extend(_collision_problems(names))
        problems.extend(
            await self._cycle_problems(ctx, pins.delegates, agent_id=agent_id, root_name=spec.name)
        )
        return problems

    async def _specialist_problems(self, ctx: AuthContext, specialist: SpecialistSpec) -> list[str]:
        """Everything wrong with a specialist defined inside this agent.

        The same checks the parent's own bindings and collections get, through the
        same helpers rather than a copy of them. A specialist is a typed subset of
        an agent, and a second validator for it would be a second set of rules to
        keep in step - which is how a specialist becomes the quiet route to a
        capability the organization never granted, a key the publisher cannot
        read, or a collection or a skill nobody shared with them. It is the
        tempting place to smuggle exactly those in, precisely because nobody
        thinks of it as an agent.

        Every problem carries the specialist's name. A Builder form has one input
        per specialist and cannot point at the right one otherwise.
        """
        problems: list[str] = []
        for binding in specialist.capabilities:
            problems.extend(await self._binding_problems(ctx, binding))
        problems.extend(await self._collection_problems(ctx, specialist.collection_ids))
        problems.extend(await self._skill_problems(ctx, specialist.skill_ids))
        # A specialist naming no profile runs on the parent's, which publish has
        # already checked - so only a profile it *did* name is a reference that
        # can be broken, or borrowed from another organization.
        if specialist.model_profile_id is not None:
            problems.extend(await self._model_profile_problems(ctx, specialist.model_profile_id))
        return [f"Specialist '{specialist.name}': {problem}" for problem in problems]

    async def _resolve_pins(self, ctx: AuthContext, refs: Sequence[SubagentRef]) -> _ResolvedPins:
        """Every way a pin to a published delegate can be wrong.

        A delegate runs inside this agent's run, for everyone who can run this
        agent, so pinning one lends it out exactly as binding a collection does -
        and the publisher has to be able to run it themselves. "Agent not found"
        therefore covers a missing row, another organization's row, and a row
        this publisher may not run, deliberately indistinguishably: a refusal
        that read differently would map the organization's private agents one
        guess at a time.

        The version is checked to belong to that agent as well as to exist. A
        version id from another agent is a cross-tenant read wearing a
        valid-looking UUID, and an existence check alone would happily run it.

        The handle each resolved pin comes back with is the agent row's `slug`,
        which is in hand because the row had to be read for the check above. It is
        read rather than derived for the reason :func:`_collision_problems`
        explains: the row owns the handle, and a name is not it.

        Returns:
            The pins that resolved, their handles, and the problems.
        """
        delegates: list[_PinnedDelegate] = []
        handles: list[str] = []
        problems: list[str] = []
        for ref in refs:
            delegate = await agent_repo.get(
                self.db, ref.agent_id, organization_id=ctx.organization_id
            )
            if delegate is None or not await resolve_access(
                self.db, ctx, delegate, Perm.AGENTS_RUN, resource_type=AGENT
            ):
                problems.append(f"Agent not found: {ref.agent_id}")
                continue
            if delegate.status == AgentStatus.ARCHIVED.value:
                problems.append(
                    f"Agent '{delegate.name}' is archived, so nothing can delegate to it"
                )
                continue
            resolved = await self._resolve_pin(ctx, ref)
            if resolved is None:
                problems.append(
                    f"Agent '{delegate.name}' has no published version "
                    f"{ref.agent_version_id} to pin"
                )
                continue
            delegates.append(resolved)
            handles.append(delegate.slug)
        return _ResolvedPins(delegates=delegates, handles=handles, problems=problems)

    async def _resolve_pin(self, ctx: AuthContext, ref: SubagentRef) -> _PinnedDelegate | None:
        """The version a pin names, if it exists and belongs to the agent named.

        Answers `None` rather than raising, so the same lookup serves the pin
        check - which reports it - and the walk into an already published
        delegate, which does not. A stored pin whose version was deleted fails
        *that* agent's run, loudly, naming it; refusing this publish for it would
        block a parent on a problem only the delegate's author can fix, in a spec
        this publisher may not even be able to see.
        """
        version = await agent_repo.get_version(
            self.db, ref.agent_version_id, organization_id=ctx.organization_id
        )
        if version is None or version.agent_id != ref.agent_id:
            return None
        return _PinnedDelegate(
            agent_id=ref.agent_id,
            version_id=version.id,
            spec=AgentSpec.model_validate(version.spec),
        )

    async def _cycle_problems(
        self,
        ctx: AuthContext,
        pinned: Sequence[_PinnedDelegate],
        *,
        agent_id: UUID | None,
        root_name: str,
    ) -> list[str]:
        """Delegation chains that come back to an agent already in them.

        `max_depth` bounds how deep one delegation goes, not whether the graph
        loops, so a cycle is not a bounded waste - it is a run that spends the
        parent's budget delegating to itself until something else stops it. And it
        is created by the publish that closes it, which is why the walk needs to
        know whose spec this is: `A -> B -> A` cannot be seen from B's stored
        version, because the pin that closes the loop is the one being added.

        The chain is named because "there is a cycle" is unactionable; what the
        person needs to know is which pin to remove.

        Each pin is followed to the *version it names*, never to the delegate's
        current draft: what a published parent will actually call is frozen, so a
        loop somebody has since edited out of a draft is still a loop here.

        Bounded twice. Nothing is expanded twice, so a cycle already sitting in
        stored data terminates the walk rather than hanging publish. And after
        :data:`_MAX_DELEGATION_NODES` versions it stops and says so, because the
        number of pins is not bounded by the spec and every one of them is a read
        inside publish's transaction.
        """
        problems: list[str] = []
        stack = [
            _DelegationStep(
                delegate=delegate,
                chain=(root_name,),
                # The agent being published is the first ancestor, when it is
                # known. Nothing is when a draft is checked outside a publish.
                ancestors=frozenset() if agent_id is None else frozenset({agent_id}),
            )
            for delegate in pinned
        ]
        expanded: set[tuple[UUID, UUID]] = set()
        while stack:
            step = stack.pop()
            chain = (*step.chain, step.delegate.spec.name)
            if step.delegate.agent_id in step.ancestors:
                problems.append(f"Delegation comes back to where it started: {' -> '.join(chain)}")
                continue
            node = (step.delegate.agent_id, step.delegate.version_id)
            if node in expanded:
                continue
            if len(expanded) >= _MAX_DELEGATION_NODES:
                problems.append(
                    f"This agent reaches more than {_MAX_DELEGATION_NODES} pinned delegate "
                    "versions, which is more than publish can check. Delegate to fewer agents."
                )
                break
            expanded.add(node)
            ancestors = step.ancestors | {step.delegate.agent_id}
            for ref in step.delegate.spec.subagents:
                deeper = await self._resolve_pin(ctx, ref)
                if deeper is not None:
                    stack.append(_DelegationStep(delegate=deeper, chain=chain, ancestors=ancestors))
        return problems

    async def publish(
        self, ctx: AuthContext, agent_id: UUID, *, note: str | None = None
    ) -> AgentVersion:
        """Validate the draft and freeze it as the version that runs."""
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        spec = AgentSpec.model_validate(agent.draft_spec)
        await self.validate_spec(ctx, spec, agent_id=agent.id)

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
        await self.validate_spec(ctx, spec, agent_id=agent.id)

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
