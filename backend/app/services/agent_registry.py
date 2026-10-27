"""Agent registry service - create, edit, publish, roll back.

The lifecycle this enforces is the whole reason agents are two tables:

    edit draft -> validate -> publish (freeze a version) -> run that version

Validation happens at publish, never at run time. An agent that references a
deleted collection or an ungranted scope is refused while someone is looking at
a form and can fix it, rather than at 3am in a customer conversation.

Rolling back publishes a *new* version copied from an old one. The alternative -
moving a pointer backwards - would make run history lie about what was live.
"""

import contextlib
import logging
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_ai_harness.compaction import resolve_context_window
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import prompt_variables
from app.agents.capabilities import (
    FRAMEWORK_TOOL_NAMES,
    TOOL_NAME_PATTERN,
    CapabilityDef,
    all_capabilities,
)
from app.agents.capabilities import get as get_capability
from app.agents.capabilities._generated import MEDIA_TOOL_NAMES
from app.agents.capabilities.approval import ungateable_tool_problems
from app.agents.capabilities.browser_use import (
    WebBrowserConfig,
    connection_problems,
    validate_cdp_url,
)
from app.agents.capabilities.browser_use._route import check_address
from app.agents.capabilities.coding_agent import CODING_AGENT_ID, CodingAgentConfig
from app.agents.capabilities.follow_ups import FollowUpsConfig
from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.mcp import PLATFORM_MCP_PREFIX, prefix_collisions
from app.agents.model_resolver import lacks_key
from app.agents.spec import (
    SPEC_VERSION,
    AgentSpec,
    BudgetSpec,
    CapabilityBindingSpec,
    McpServerRef,
    OrgMcpServerRef,
    PersonalMcpServerRef,
    PlatformMcpServerRef,
    SpecialistSpec,
    SpeechToTextSpec,
    SubagentRef,
    VoiceSpec,
)
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.field_errors import field_problems, refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.core.secret_kinds import SecretKind
from app.db.locks import LockScope, hold_subject
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.credential import ModelProfile
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.repositories import (
    agent_environment_repo,
    agent_exposure_repo,
    agent_repo,
    agent_trigger_repo,
    context_repo,
    credential_repo,
    external_agent_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    member_repo,
    organization_assistant_repo,
    organization_secret_repo,
    resource_grant_repo,
    sandbox_connection_repo,
    skill_repo,
    user_repo,
)
from app.schemas.agent import (
    MAX_CATEGORIES,
    MAX_TAGS,
    AgentCeiling,
    AgentRead,
    AgentTemplateCatalog,
    AgentTemplateRead,
    AgentVersionRead,
    CapabilityEnabled,
    DelegationTree,
    DelegationTreeNode,
    PublishedModel,
    TemplateIndustryRead,
    TemplateInstallResult,
    normalize_labels_query,
)
from app.services import (
    agent_templates,
    mcp_catalog,
    provider_keys,
    realtime_models,
    skill_library,
    speech_to_text,
)
from app.services.access import (
    AGENT,
    COLLECTION,
    CONTEXT,
    MCP_CONNECTION,
    SECRET,
    SKILL,
    accessible_ids,
    resolve_access,
    visible_resource_ids,
)
from app.services.channels.base import ROOM_HANDLES
from app.services.deployment_settings import DeploymentSettingsService
from app.services.file_storage import (
    IMAGE_MIME_TYPES,
    MAX_AVATAR_SIZE,
    avatar_filename,
    get_file_storage,
)
from app.services.model_outputs import model_outputs, not_chat_refusal
from app.services.model_profile import MAX_FALLBACK_DEPTH
from app.services.notifications import NotificationService
from app.services.resource_usage import groups_sharing
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import sandbox_config
from app.services.sharing import SharingService
from app.services.skills import SkillService
from app.services.speech_to_text_settings import SpeechToTextSettingsService

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
#
# `conversations:read` is the same kind of lever for `conversation_search`: it is
# the one switch that stops agents reading past conversations across the whole
# deployment, for somewhere that considers a transcript too sensitive to be
# searchable however narrowly the corpus is scoped.
DEFAULT_GRANTED_SCOPES = frozenset(
    {
        "knowledge:read",
        "conversations:read",
        "web:read",
        "web:fetch",
        "web:browse",
        "code:execute",
        "sandbox:execute",
        "agents:delegate",
    }
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
        # The deployment's own sandbox service, set up here when it runs one and
        # nobody has opened the Sandboxes page yet - the same row a run would set up.
        connection = await SandboxConnectionService(db).ensure_local_connection(ctx.organization_id)
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


def _coding_agent_problems(spec: AgentSpec) -> list[str]:
    """A coding agent with nowhere to run its harness.

    Claude Code and Codex run as commands in the agent's sandbox, so they need a
    container-backed one with the shell on. Every other shape publishes and then
    answers each task with "no shell here", which is the run-time surprise
    publish exists to prevent.
    """
    if not any(binding.id == CODING_AGENT_ID and binding.enabled for binding in spec.capabilities):
        return []
    config = sandbox_config(spec)
    if config is None or config.backend != "service" or not config.include_execute:
        return [
            "The coding agent runs in the agent's sandbox, so it needs the Sandbox "
            "capability on a sandbox connection with shell commands allowed."
        ]
    return []


_READ_PERMS = frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_RUN})
"""What `get` may be asked for on the assistant by anyone who reaches it."""


async def _browser_problems(config: BaseModel | None, *, has_secret: bool) -> list[str]:
    """A `cdp_url` the operator has not vetted, or a proxy or hosted browser that cannot be used.

    The `cdp_url` is an exact match against `BROWSER_CDP_ALLOWED_HOSTS`;
    `validate_cdp_url` says why the allowlist is the control there rather than the
    SSRF guard. A proxy or hosted browser is an address on the open internet, so
    it gets the SSRF guard - off the event loop, since it resolves DNS. Every
    binding passes through here - a spec's own and each inline specialist's - so
    a specialist cannot smuggle one past.
    """
    if not isinstance(config, WebBrowserConfig):
        return []
    try:
        validate_cdp_url(config)
    except ValueError as exc:
        return [f"The web browser's endpoint cannot be used: {exc}."]
    problems = connection_problems(config, has_secret=has_secret)
    if problems:
        return problems
    try:
        if config.connection == "proxy":
            await check_address(config.proxy_url, kind="proxy")
        elif config.connection == "hosted":
            await check_address(config.hosted_url, kind="hosted")
    except ValueError as exc:
        return [f"The browser's {config.connection} address cannot be used: {exc}"]
    return []


def _variable_problems(spec: AgentSpec) -> _SpecProblems:
    """Variables the instructions cannot fill, and custom ones that cannot be defined (#2065).

    Refused here rather than left as literal braces for a run to send the model:
    `{{custmer_name}}` reaching a customer is the typo nobody sees until then.
    """
    problems = _SpecProblems()

    def refuse(field_name: str, message: str) -> None:
        problems.messages.append(message)
        problems.fields.append({"field": field_name, "message": message})

    for name in prompt_variables.unknown_variables(spec):
        refuse("instructions", f"The instructions use {{{{{name}}}}}, which is not a variable")
    seen: set[str] = set()
    for index, variable in enumerate(spec.variables):
        if variable.name in prompt_variables.SYSTEM_NAMES:
            refuse(
                f"variables.{index}.name",
                f"'{variable.name}' is a system variable and cannot be redefined",
            )
        elif variable.name in seen:
            refuse(f"variables.{index}.name", f"'{variable.name}' is defined twice")
        seen.add(variable.name)
    if spec.time_zone not in (
        prompt_variables.SYSTEM_TIME_ZONE,
        prompt_variables.PERSON_TIME_ZONE,
    ) and not prompt_variables.is_time_zone(spec.time_zone):
        refuse("time_zone", f"'{spec.time_zone}' is not a time zone")
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

    # The count above only sees this capability's own tools, and the framework
    # adds its own beside them: a run with any deferred capability carries
    # `load_capability`, so a *rename* onto that name is a duplicate Pydantic AI
    # refuses mid-turn rather than a collision this loop can see. Renames only -
    # `skills` declares `load_capability` itself, because that call is where an
    # approval on opening a skill has to sit.
    taken = sorted(
        {override.name for override in binding.tool_overrides.values() if override.name is not None}
        & FRAMEWORK_TOOL_NAMES
    )
    if taken:
        problems.append(
            f"Capability '{binding.id}' renames a tool to {', '.join(taken)}, which the "
            "framework provides itself - two tools of that name abort the turn"
        )

    # A media tool's name is read as that tool's everywhere a step is shown, so
    # another tool may not take it. Its own tool keeping it is no rename at all.
    impostors = sorted(
        override.name
        for tool_id, override in binding.tool_overrides.items()
        if override.name in MEDIA_TOOL_NAMES and override.name != tool_id
    )
    if impostors:
        problems.append(
            f"Capability '{binding.id}' renames a tool to {', '.join(impostors)}, the name "
            "of the tool that stores generated media - only that tool may carry it"
        )

    return problems


@dataclass
class _SpecProblems:
    """Everything wrong with a spec: a line to read, and where to put it.

    `messages` is the list the Builder shows and has always been the whole of
    the answer. `fields` is the same refusal aimed at an input, in the shape
    `frontend/src/lib/api-error.ts` marks one from - because a capability's
    configuration is a *form*, and "Capability 'knowledge': Invalid
    configuration for capability 'knowledge'" leaves the reader to work out
    which of its boxes is wrong.

    Both, never one. `validate_spec` reports every problem at once and most of
    them are broken references with no input to mark, so a field problem adds a
    line as well: the message is what a form that does not render that field
    still has to show (#882).
    """

    messages: list[str] = field(default_factory=list)
    fields: list[dict[str, str]] = field(default_factory=list)

    def add(self, messages: Sequence[str]) -> None:
        """Problems with nothing to mark - a broken reference, a missing model."""
        self.messages.extend(messages)

    def merge(self, other: _SpecProblems) -> None:
        self.messages.extend(other.messages)
        self.fields.extend(other.fields)

    def within_specialist(self, name: str) -> _SpecProblems:
        """The same problems, said about a specialist defined inside this agent.

        Both halves are scoped, or a mistake in a specialist's copy of
        `knowledge` would mark the parent's own `knowledge` card - the Builder
        renders one form per specialist and they configure the same
        capabilities.
        """
        return _SpecProblems(
            [f"Specialist '{name}': {message}" for message in self.messages],
            [
                {**problem, "field": f"specialists.{name}.{problem['field']}"}
                for problem in self.fields
            ],
        )


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
    version: int
    spec: AgentSpec


@dataclass
class _TreeWalk:
    """Shared state for one delegation-tree walk.

    The caches are what make a diamond cheap - a delegate two parents pin is
    read and access-checked once - and `capped` is how the walk tells the
    response it stopped at :data:`_MAX_DELEGATION_NODES` rather than at the
    bottom of the graph.
    """

    rows: dict[UUID, Agent | None] = field(default_factory=dict)
    pins: dict[tuple[UUID, UUID], _PinnedDelegate | None] = field(default_factory=dict)
    count: int = 0
    capped: bool = False


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


def _with_starter_instructions(spec: AgentSpec) -> AgentSpec:
    """A spec with no instructions, given the starter agent's.

    An agent with no instructions still answers - as whatever the underlying
    model is by default, which is a different product on every provider and
    changes when the model is upgraded - so a new one opens with the starter's
    prompt rather than an empty box. Applied at creation rather than as a field
    default, because a spec imported with an empty prompt means an empty prompt.
    """
    template = agent_templates.get(agent_templates.STARTER_TEMPLATE)
    if template is None:  # pragma: no cover - the template ships with the image
        return spec
    return spec.model_copy(update={"instructions": template.instructions})


def _without_unselectable(spec: AgentSpec) -> AgentSpec:
    """The spec with any capability a spec may not bind taken out of it.

    `channel_tools` is chosen per bound bot rather than on the agent, so the
    Toolbox does not offer it and nothing in the product can add it. What the
    product *can* do is send it back: a browser holding a draft loaded before
    the capability moved re-posts the whole spec on the next save, and the
    binding returns.

    Dropped on write rather than refused at publish, and the difference is a
    dead end. A refusal names a switch the Builder does not show, so there is no
    way to act on it - the binding cannot be removed from the only screen that
    edits capabilities. Stripping it here means a stale tab heals itself the
    next time anybody saves.

    Not a fallback papering over a bug: the binding does nothing at run time
    either way, because the run assembles its own from the exposure that
    admitted it. Logged rather than silent, because a YAML import that named one
    has lost something it asked for.
    """
    # Membership rather than a lookup per binding, because `get_capability`
    # raises on an id it does not know - and a draft naming a capability that
    # does not exist has to stay saveable. That one is publish's to refuse;
    # this function only removes what exists and may not be bound.
    unselectable = {definition.id for definition in all_capabilities() if not definition.selectable}
    kept = [binding for binding in spec.capabilities if binding.id not in unselectable]
    if len(kept) == len(spec.capabilities):
        return spec
    dropped = sorted({binding.id for binding in spec.capabilities} & unselectable)
    logger.info("spec_dropped_unselectable_capabilities", extra={"capabilities": dropped})
    return spec.model_copy(update={"capabilities": kept})


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


def _subagents_config(spec: AgentSpec) -> SubagentsConfig | None:
    """The delegation policy this spec runs under, or None when it cannot delegate.

    None covers both a binding that is absent or switched off and one whose
    config does not parse: a policy nobody can read delegates nothing, and the
    parse failure itself is `_binding_problems`' report to make, not this
    reader's to repeat.
    """
    binding = delegation_binding(spec)
    if binding is None:
        return None
    try:
        return SubagentsConfig.model_validate(binding.config)
    except ValidationError:
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


def _config_problems(capability_id: str, refusal: BadRequestError) -> _SpecProblems:
    """A capability's refused configuration, as a line *and* as its inputs.

    `validate_config` names each field that broke a rule, and publish validation
    used to keep only `refusal.message` - so `default_top_k: 999` reached the
    Builder as "Capability 'knowledge': Invalid configuration for capability
    'knowledge'" and no box was ever marked. Draft saving does not validate a
    config schema at all, which makes this the path a Builder submission
    actually takes (found reviewing #892).

    The path is qualified by the capability because the form is per capability
    and two of them can hold a field of the same name; `SchemaForm` keys its
    errors by the bare field, and `capabilityConfigErrors` in
    `frontend/src/lib/agent-spec.ts` is what takes one apart again.
    """
    fields = refusal.details.get("fields", []) if refusal.details else []
    return _SpecProblems(
        [f"Capability '{capability_id}': {refusal.message}"],
        [
            {**problem, "field": f"capabilities.{capability_id}.{problem['field']}"}
            for problem in fields
        ],
    )


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

    An agent named "Channel" or "Everyone" gets a suffix rather than the bare
    handle. Those address the *room* on every chat platform, so `parse_mention`
    refuses them before they can reach an agent - and a handle nothing can ever
    say is worse than an ugly one, because nothing about the agent would look
    wrong.
    """
    slug = _SLUG_ALLOWED.sub("-", name.strip().lower())
    slug = _SLUG_TRIM.sub("-", slug).strip("-")
    slug = slug[:64] or "agent"
    return f"{slug}-agent" if slug in ROOM_HANDLES else slug


def _window_of(profile: ModelProfile | None) -> int | None:
    """The context window this profile's model accepts, or `None`.

    The profile's recorded number first: it is what the provider's own listing
    published when somebody added the model, and it beats the pricing registry -
    which records 1,000,000 for `anthropic:claude-sonnet-4-5` against a real
    200,000, wrong in the direction that lets a run reach the ceiling.

    The registry is the fallback for a profile older than that column. Nothing is
    invented past it: a conservative default here would be drawn as a percentage,
    and a share against a window nobody could resolve is a guess presented as a
    measurement.
    """
    if profile is None:
        return None
    if profile.context_length is not None:
        return profile.context_length
    return resolve_context_window(f"{profile.provider}:{profile.model}")


def _published_models(
    profile_ids: dict[UUID, UUID], profiles: dict[UUID, ModelProfile]
) -> dict[UUID, PublishedModel]:
    """The model each published version runs on, by version id.

    A version whose profile has been deleted is absent rather than a null entry:
    the frozen spec still names an id, but nothing can say what it was, and a
    picker prefilled from a gap would name a model the profile no longer is.
    """
    return {
        version_id: PublishedModel(
            profile_id=profile.id,
            provider=profile.provider,
            model=profile.model,
            label=profile.label,
        )
        for version_id, profile_id in profile_ids.items()
        if (profile := profiles.get(profile_id)) is not None
    }


def _yaml_refusal(exc: yaml.YAMLError) -> str:
    """Where the document stopped parsing, without quoting any of it.

    `str()` on a marked YAML error includes the offending source line, and the
    document is somebody's spec - instructions, a `secret_id`, whatever they
    were editing when it broke. So the position is reported and the text is not:
    it is already in front of the person who wrote it
    (`.claude/rules/exceptions-security.md`). A `ReaderError` - a control
    character in the file - carries a byte offset and no mark, which is why the
    line is optional rather than assumed.

    In the sentence rather than beside it: the position used to be `details`
    keys of its own, which nothing has ever read (#891), and a line number is
    only worth reporting to the reader who has the document open.
    """
    refusal = "This spec is not valid YAML"
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return refusal
    return f"{refusal} - line {mark.line + 1}, column {mark.column + 1}"


def _parse_spec_yaml(text: str) -> AgentSpec:
    """Read a spec written or edited outside the Builder.

    Every field rule in `AgentSpec` exists to explain what is wrong with a spec,
    and none of those explanations used to reach the person who wrote one: a
    pydantic `ValidationError` is a `ValueError` but not a
    `RequestValidationError`, so nothing between the parse and the ASGI boundary
    mapped it and a typo answered 500 with a traceback in the log, as though the
    platform had broken rather than the file (#873). Bad input is this path's
    ordinary case - somebody is editing YAML by hand and iterating.

    Raises:
        BadRequestError: If the document does not parse, is not a mapping, or
            breaks a field rule - carrying the field path a form can mark, and
            no copy of what was submitted. All three answer in the one shape,
            `details["fields"]`: a field rule below `yaml`, and a document that
            never parsed against `yaml` itself, since the editor it was typed
            into is the only input there is to blame.
    """
    try:
        return AgentSpec.from_yaml(text)
    except ValidationError as exc:
        raise BadRequestError(
            message="This spec does not match the agent spec format",
            details={"fields": field_problems(exc.errors(), root="yaml")},
        ) from exc
    except yaml.YAMLError as exc:
        raise refused_field("yaml", _yaml_refusal(exc)) from exc
    except ValueError as exc:
        raise refused_field("yaml", str(exc)) from exc


class AgentRegistryService:
    """Manage an organization's agents."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        perm: Perm = Perm.AGENTS_VIEW,
        for_update: bool = False,
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
        if for_update:
            agent = await agent_repo.get(
                self.db, agent_id, organization_id=ctx.organization_id, for_update=True
            )
            if agent is None or not await resolve_access(
                self.db, ctx, agent, perm, resource_type=AGENT
            ):
                raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
        if perm not in _READ_PERMS and not ctx.has(Perm.ORG_SETTINGS):
            await self._refuse_the_assistant(agent)
        return agent

    async def _refuse_the_assistant(self, agent: Agent) -> None:
        """Refuse changing the organization's assistant without `org:settings`.

        It is installed as an ordinary organization-wide agent, so a Builder's
        `agents:edit` reaches it through the generic routes - and everybody who
        opens the corner widget runs it with their own authority. Its spec is
        changed in the Builder, behind the gate `/assistant` has.

        Raises:
            AuthorizationError: The agent is the organization's assistant.
        """
        if await organization_assistant_repo.for_agent(self.db, agent.id) is not None:
            raise AuthorizationError(
                message="Only an administrator can change the AI Architect",
                details={"agent_id": agent.id},
            )

    async def may_run(self, ctx: AuthContext, agent: Agent) -> bool:
        """Whether this caller may run this agent - the floor to create a trigger on it.

        The per-resource counterpart to the `can_run` the listing fills in batch:
        the detail route reads it for one agent it already loaded. It resolves the
        run access the same way, through `resolve_access`, so a Viewer holding an
        explicit run grant reads true here where the role-level check would refuse
        them. The access call stays in the service rather than the route, which is
        the layering every other per-resource decision here already follows.
        """
        return await resolve_access(self.db, ctx, agent, Perm.AGENTS_RUN, resource_type=AGENT)

    async def _visible_scope(
        self, ctx: AuthContext, *, shared_with_me: bool
    ) -> tuple[bool, list[UUID]]:
        """Whether the caller's role reaches every agent, and the ids granted to them."""
        # `None` is `visible_resource_ids` saying the role already reaches every
        # agent, which is exactly what `see_all` tells the query - so both come
        # from the one call rather than from the scope being read twice and the
        # two answers being trusted to agree.
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=AGENT, perm=Perm.AGENTS_VIEW
        )
        if shared is not None:
            return False, shared
        if not shared_with_me:
            return True, []
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
        return True, grant_ids

    async def any_visible(self, ctx: AuthContext) -> bool:
        """Whether the caller sees at least one agent: the listing's own scope, one row of it."""
        see_all, grant_ids = await self._visible_scope(ctx, shared_with_me=False)
        agents, _total = await agent_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=grant_ids,
            limit=1,
        )
        return bool(agents)

    async def list_labels(
        self, ctx: AuthContext, *, shared_with_me: bool = False, include_archived: bool = False
    ) -> tuple[list[str], list[str]]:
        """The categories and tags the listing can be filtered to, for the caller.

        Scoped exactly like `list_agents` and unaffected by its filter and paging.
        """
        see_all, grant_ids = await self._visible_scope(ctx, shared_with_me=shared_with_me)
        return await agent_repo.list_visible_labels(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            include_archived=include_archived,
        )

    async def list_agents(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        include_archived: bool = False,
        categories: Sequence[str] = (),
        tags: Sequence[str] = (),
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentRead], int]:
        """Agents visible to the caller under their role scope and grants.

        `shared_with_me` narrows to what was deliberately shared with them -
        org-visible or explicitly granted, and not their own.

        `categories`/`tags` are the raw discovery-filter query params. They are
        folded once here with the tolerant query normalizer (over-length items
        dropped, capped per facet, never raising) and threaded to `list_visible`,
        which overlaps them against the row - a narrowing on top of the isolation
        the query already enforces.

        A facet where every supplied value was invalid (too long, once folded)
        normalizes to `None`, not `[]`: it must not fall back to "no predicate"
        and broaden into an unfiltered listing, so that case returns empty here
        rather than reaching `list_visible` at all.
        """
        norm_categories = normalize_labels_query(list(categories), max_items=MAX_CATEGORIES)
        norm_tags = normalize_labels_query(list(tags), max_items=MAX_TAGS)
        if norm_categories is None or norm_tags is None:
            return [], 0
        see_all, grant_ids = await self._visible_scope(ctx, shared_with_me=shared_with_me)
        agents, total = await agent_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=see_all,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            include_archived=include_archived,
            categories=norm_categories,
            tags=norm_tags,
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
        version_ids = [agent.current_version_id for agent in agents if agent.current_version_id]
        budget_caps = await agent_repo.published_budget_caps(self.db, version_ids=version_ids)
        starters = await agent_repo.published_starters(self.db, version_ids=version_ids)
        profile_ids = await agent_repo.published_model_profiles(self.db, version_ids=version_ids)
        profiles = (
            await credential_repo.get_profiles_by_ids(
                self.db, list(set(profile_ids.values())), organization_id=ctx.organization_id
            )
            if profile_ids
            else {}
        )
        windows = await self._context_windows(version_ids, profile_ids, profiles)
        published_models = _published_models(profile_ids, profiles)
        # Which of these the caller may run, in one grant query for the page - the
        # floor for offering "new trigger" on a card. A grant widens it per row, so
        # a Viewer shared run on one agent sees the control there and nowhere else.
        runnable = await accessible_ids(self.db, ctx, agents, Perm.AGENTS_RUN, resource_type=AGENT)
        groups = await groups_sharing(
            self.db, ctx, resource_type=AGENT, resource_ids=[agent.id for agent in agents]
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
                avatar_color=agent.avatar_color,
                categories=agent.categories,
                tags=agent.tags,
                can_run=agent.id in runnable,
                shared_user_count=shared_counts.get(agent.id, 0),
                shared_groups=groups[agent.id],
                channels=surfaces.get(agent.id, []),
                budget_monthly_usd=(
                    budget_caps.get(agent.current_version_id) if agent.current_version_id else None
                ),
                context_window_tokens=(
                    windows.get(agent.current_version_id) if agent.current_version_id else None
                ),
                published_model=(
                    published_models.get(agent.current_version_id)
                    if agent.current_version_id
                    else None
                ),
                starters=(
                    starters.get(agent.current_version_id, []) if agent.current_version_id else []
                ),
                created_at=agent.created_at,
                updated_at=agent.updated_at,
            )
            for agent in agents
        ]
        return rows, total

    async def _context_windows(
        self,
        version_ids: list[UUID],
        profile_ids: dict[UUID, UUID],
        profiles: dict[UUID, ModelProfile],
    ) -> dict[UUID, int | None]:
        """How many tokens each published version's model accepts, by version id.

        Resolved for the listing rather than per run, because the *share* of a
        window is drawn where the model is known: the chat lets somebody switch
        model between turns, and a share carried forward from another model reads
        "50%" for a history that is really at 390% of the new one.

        Three sources, in this order. The `compaction` binding's own
        `context_window` first: an author sets it precisely because the resolved
        number is wrong for them, and it is what the compaction *trigger* already
        uses - a gauge dividing by something else would describe a different
        ceiling than the one the agent acts on. Then the profile's
        `context_length`, which is what its provider published when the model was
        added, and which beats the pricing registry - that records 1,000,000 for
        `anthropic:claude-sonnet-4-5` against a real 200,000. The registry is the
        fallback for a profile older than that column.

        `None` where neither can say, and a surface then draws no share at all
        rather than one against a conservative guess.

        `profile_ids` (version to its published profile) and `profiles` (profile
        to its row) are loaded once by the caller, because the published-model
        summary the listing also carries is read off the same two lookups.
        """
        overrides = await agent_repo.published_compaction_windows(self.db, version_ids=version_ids)
        return {
            version_id: overrides.get(version_id) or _window_of(profiles.get(profile_id))
            for version_id, profile_id in profile_ids.items()
        } | {
            version_id: window
            for version_id, window in overrides.items()
            if version_id not in profile_ids
        }

    async def templates(self, ctx: AuthContext) -> AgentTemplateCatalog:
        """The shipped agent templates, with what this organization already has.

        `installed` is a slug match, because the slug is what an install would
        collide on - two agents cannot share one, since a slug is how an agent is
        mentioned in a channel.
        """
        taken = await agent_repo.list_slugs(self.db, organization_id=ctx.organization_id)
        return AgentTemplateCatalog(
            industries=[
                TemplateIndustryRead(
                    id=industry.id,
                    templates=[
                        AgentTemplateRead(
                            key=template.key,
                            name=template.name,
                            description=template.description,
                            capabilities=[binding["id"] for binding in template.capabilities],
                            skills=list(template.skills),
                            mcp=list(template.mcp),
                            attach=list(template.attach),
                            budget_usd=template.budget_usd,
                            installed=slugify(template.name) in taken,
                        )
                        for template in industry.templates
                    ],
                )
                for industry in agent_templates.catalog()
            ]
        )

    async def template_skills(
        self, ctx: AuthContext, template: agent_templates.AgentTemplate
    ) -> list[Skill]:
        """The skills a template expects, installed where missing and readable by `ctx`.

        Shared by a template install and the AI Architect's own install (#2069), so
        both bind exactly the skills a person installing the template would get.
        """
        # A bundled skill is seeded into every organization when it is created,
        # so there is nothing to install - only a row to find by its name.
        # Everything else is a gallery key and is installed first.
        bundled = {
            key: entry.name
            for key in template.skills
            if (entry := skill_library.get(key)) is not None
        }
        gallery_keys = [key for key in template.skills if key not in bundled]
        if gallery_keys:
            await SkillService(self.db).install_gallery(ctx, gallery_keys)

        wanted = sorted(
            {
                *bundled.values(),
                *(
                    entry.name
                    for gallery_key in gallery_keys
                    if (entry := skill_library.gallery_get(gallery_key)) is not None
                ),
            }
        )
        # Only rows the installer may read: a copy its owner made private since
        # it was seeded would otherwise be bound, reported as installed, and then
        # refused at publish as a skill that does not exist - the check publish
        # makes, made here first.
        return [
            row
            for name in wanted
            if (
                row := await skill_repo.get_by_name(
                    self.db, name, organization_id=ctx.organization_id
                )
            )
            is not None
            and await resolve_access(self.db, ctx, row, Perm.SKILLS_VIEW, resource_type=SKILL)
        ]

    async def _from_the_starter(self, ctx: AuthContext, spec: AgentSpec) -> AgentSpec:
        """A new agent made what the starter agent is, for the console's New agent (#2301).

        It starts as the organization's own AgenticOS agent does: its
        instructions, which lead with the agent's own `{{agent_name}}`, and
        whatever of its capabilities, skills, platform tools, starters and budget
        the caller left empty. The author then edits the first paragraph and
        switches off what this agent should not do. Asked for rather than implied
        by an empty spec: an integration creating a bare agent over the API is
        not asking for a sandbox, the platform's tools and a budget.
        """
        template = agent_templates.get(agent_templates.STARTER_TEMPLATE)
        if template is None:  # pragma: no cover - the template ships with the image
            return spec
        update: dict[str, Any] = {
            "instructions": spec.instructions
            if spec.instructions.strip()
            else template.instructions
        }
        if not spec.capabilities:
            update["capabilities"] = agent_templates.for_this_deployment(template.capabilities)
        if not spec.mcp_servers:
            update["mcp_servers"] = list(template.mcp_servers)
        if not spec.skill_ids:
            update["skill_ids"] = [row.id for row in await self.template_skills(ctx, template)]
        if not spec.starters:
            update["starters"] = list(template.starters)
        if spec.budget is None and template.budget_usd is not None:
            update["budget"] = {"monthly_usd": template.budget_usd}
        return AgentSpec.model_validate({**spec.model_dump(), **update})

    async def install_template(
        self, ctx: AuthContext, key: str, *, visibility: Visibility = Visibility.ORG
    ) -> TemplateInstallResult:
        """Create a draft agent from a shipped template, with its skills.

        Visible to the organization, as an agent from the create form is. The
        reason `create` defaults to private - a copy must not publish somebody's
        private instructions to the tenant - does not reach a template: its
        instructions ship with the product. Installed private, every template
        agent had to be found and re-shared by hand before a colleague could see it.

        A **draft**, deliberately. The template cannot name a model - this
        platform has no organization-wide default, because a model an agent did
        not choose is one somebody else's change can swap underneath it - and it
        cannot name a knowledge collection it has never seen. Publishing an agent
        missing either would produce answers from nowhere, confidently.

        The skills it expects are installed first, from the gallery, and skipped
        where the organization already has them. A bundled skill is bound where
        the organization still has it, and left out where somebody deleted it. Its MCP suggestions are returned
        rather than bound: a connection needs somebody to authorise it.

        Raises:
            NotFoundError: If no such template ships with this deployment.
            AlreadyExistsError: If the slug is taken - which is what installing
                the same template twice would do, and the second agent would be
                indistinguishable from the first in a channel.
        """
        template = agent_templates.get(key)
        if template is None:
            raise NotFoundError(message="No such agent template", details={"key": key})

        rows = await self.template_skills(ctx, template)

        spec = AgentSpec(
            name=template.name,
            description=template.description,
            instructions=template.instructions,
            capabilities=agent_templates.for_this_deployment(template.capabilities),
            mcp_servers=list(template.mcp_servers),
            skill_ids=[row.id for row in rows],
            budget=(
                BudgetSpec(monthly_usd=template.budget_usd)
                if template.budget_usd is not None
                else None
            ),
            starters=list(template.starters),
        )
        agent = await self.create(ctx, spec, visibility=visibility)
        if template.avatar is not None:
            agent = await self.set_avatar(
                ctx, agent.id, file_data=template.avatar.read_bytes(), content_type="image/png"
            )
        return TemplateInstallResult(
            agent_id=agent.id,
            slug=agent.slug,
            name=agent.name,
            skills_installed=sorted(row.name for row in rows),
            attach=list(template.attach),
            suggested_mcp=list(template.mcp),
        )

    async def create(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        *,
        # The least-exposing value, deliberately. `org` is what a person picks in
        # the create form, and `AgentCreate.visibility` carries that choice to the
        # route - so the default here only ever reaches the callers that make an
        # agent without anybody choosing: a clone and a promoted specialist.
        # Defaulting those to `org` published a copy of a private agent to the
        # whole tenant, which is what a colleague then read the instructions out
        # of. A template install passes `org` itself: its instructions ship with
        # the product.
        visibility: Visibility = Visibility.PRIVATE,
        categories: list[str] | None = None,
        tags: list[str] | None = None,
        group_ids: list[UUID] | None = None,
        user_ids: list[UUID] | None = None,
        from_starter: bool = False,
    ) -> Agent:
        """Create an agent in draft.

        Visible to the organization unless the caller says otherwise. An agent is
        a thing a company builds, and one nobody else can see is the exception -
        it used to be the rule, so every agent was made invisible and then shared
        by hand, which meant the second person to look for it was told it did not
        exist. A draft cannot run and cannot be reached by an exposure either
        way, so what this decides is who can find it, not what it can do.

        Raises:
            AlreadyExistsError: If the derived slug is taken. Slugs are how agents are
                mentioned in Slack, so silently disambiguating one would route
                messages to the wrong agent.
            BadRequestError: If the organization already holds as many agents as
                the deployment allows. Null is no ceiling, which is what a
                deployment that has never set one has - see
                `DeploymentSettings.max_agents_per_organization`.
        """
        await self._refuse_past_the_ceiling(ctx)
        if from_starter:
            spec = await self._from_the_starter(ctx, spec)
        elif not spec.instructions.strip():
            spec = _with_starter_instructions(spec)
        spec = _without_unselectable(spec)

        slug = slugify(spec.name)
        if await agent_repo.get_by_slug(self.db, slug, organization_id=ctx.organization_id):
            raise AlreadyExistsError(
                message=(
                    f"The handle @{slug} is already taken. It is derived from the name and "
                    "is what an @mention resolves to, so it has to be unique and cannot be "
                    "changed later - give this agent a name that produces a different handle."
                ),
                # The handle, not the input that produced it: a conflict is a
                # fact about a row, and which of its own fields derived the
                # taken value is the form's to say - `submitFailure`'s
                # `identifiedBy`, in `frontend/src/lib/api-error.ts` (#891).
                details={"slug": slug},
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
            visibility=visibility.value,
            categories=categories or [],
            tags=tags or [],
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
        if group_ids or user_ids:
            await SharingService(self.db).restrict_to(
                ctx,
                agent,
                resource_type=AGENT,
                group_ids=group_ids or [],
                user_ids=user_ids or [],
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
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        spec = _without_unselectable(spec)
        return await agent_repo.update(
            self.db,
            agent=agent,
            update_data={
                "draft_spec": spec.model_dump(mode="json"),
                "name": spec.name,
                "description": spec.description,
            },
        )

    async def import_spec(self, ctx: AuthContext, agent_id: UUID, text: str) -> Agent:
        """Replace the draft with a spec exported into a client's own repository.

        The parse happens before the agent is read. What it refuses depends only
        on the document the caller sent, so putting it first leaks nothing about
        which agents exist and answers somebody iterating on a file without
        opening a transaction against a row they were never going to write.

        Raises:
            BadRequestError: If the document does not parse, is not a mapping, or
                breaks a field rule.
        """
        return await self.save_draft(ctx, agent_id, _parse_spec_yaml(text))

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
                reference, and a `fields` list for those a form can mark. A
                capability's configuration is the one part of a spec rendered as
                a generated form, so its refusals name the input rather than
                only the capability (#882).
        """
        problems = _SpecProblems()

        for binding in spec.capabilities:
            problems.merge(await self._binding_problems(ctx, binding))

        # A model, named. There is no organization-wide default to fall back
        # on: a model an agent did not choose is one somebody else's change can
        # swap underneath it, and "why did this get more expensive" then has no
        # answer in the agent's own history.
        if spec.model_profile_id is None:
            problems.add(["No model selected - pick one before publishing"])
        else:
            problems.add(await self.model_profile_problems(ctx, spec.model_profile_id))
        # And each reviewer's, refused here rather than when a run first reaches
        # its cadence and finds nothing to review with.
        for reviewer in spec.reviewers:
            if reviewer.model_profile_id is None:
                problems.add([f"Reviewer '{reviewer.name}': pick the model it reviews with"])
            else:
                problems.add(await self.model_profile_problems(ctx, reviewer.model_profile_id))
            if not reviewer.instructions.strip():
                problems.add([f"Reviewer '{reviewer.name}': say what it looks for"])

        problems.add(await self._collection_problems(ctx, spec.collection_ids))
        problems.add(await self._skill_problems(ctx, spec.skill_ids))
        problems.add(await self._context_problems(ctx, spec.context_ids))

        problems.add(await self._mcp_problems(ctx, spec.mcp_servers))
        problems.add(await self._observability_problems(ctx, spec))
        problems.add(await self._speech_to_text_problems(ctx, spec.speech_to_text))
        problems.add(await self._voice_problems(ctx, spec.voice))
        problems.merge(_variable_problems(spec))

        problems.add(await _sandbox_problems(self.db, ctx, spec))
        problems.add(_coding_agent_problems(spec))
        problems.merge(await self._delegation_problems(ctx, spec, agent_id=agent_id))

        if problems.messages:
            # `fields` only when there is one: an empty list is a claim that
            # nothing here can be marked, which a reader would have to tell
            # apart from a refusal that never names a field at all.
            details: dict[str, Any] = {"problems": problems.messages}
            if problems.fields:
                details["fields"] = problems.fields
            raise BadRequestError(message="This agent cannot be published yet", details=details)

    async def _binding_problems(
        self, ctx: AuthContext, binding: CapabilityBindingSpec
    ) -> _SpecProblems:
        """Everything wrong with one capability binding.

        One binding rather than a spec's list, because a specialist defined
        inside an agent has bindings too and they are the same bindings - same
        registry, same scopes, same secrets. Two loops that had to be kept in
        step would drift, and the half that drifted would be the one nobody
        thought of as an agent.
        """
        problems = _SpecProblems()
        try:
            definition = get_capability(binding.id)
        except BadRequestError:
            problems.add([f"Unknown capability: {binding.id}"])
            return problems

        missing_scopes = definition.scopes - DEFAULT_GRANTED_SCOPES
        if missing_scopes:
            problems.add(
                [
                    f"Capability '{binding.id}' needs scopes not granted here: "
                    f"{', '.join(sorted(missing_scopes))}"
                ]
            )
        try:
            config = definition.validate_config(binding.config)
        except BadRequestError as exc:
            problems.merge(_config_problems(binding.id, exc))
        else:
            problems.add(await _browser_problems(config, has_secret=binding.secret_id is not None))
            if isinstance(config, WebBrowserConfig) and config.step_model_profile_id is not None:
                problems.add(await self.model_profile_problems(ctx, config.step_model_profile_id))
            if isinstance(config, FollowUpsConfig) and config.model_profile_id is not None:
                problems.add(await self.model_profile_problems(ctx, config.model_profile_id))
            problems.add(ungateable_tool_problems(binding, definition, config))
        # A tool_approval key that matches nothing is the dangerous kind of
        # typo: it is not an error at run time, it is silence - the tool the
        # author meant to gate runs unapproved and nobody is told.
        unknown_tools = sorted(set(binding.tool_approval) - definition.tool_ids)
        if unknown_tools:
            problems.add(
                [
                    f"Capability '{binding.id}' has no tool named "
                    f"{', '.join(unknown_tools)} to set approval for"
                ]
            )
        problems.add(_tool_override_problems(binding, definition))
        problems.add(await self._secret_problems(ctx, binding, definition))
        return problems

    async def model_profile_problems(self, ctx: AuthContext, profile_id: UUID) -> list[str]:
        """Whether a named model profile is still this organization's to run on.

        And whether it is a model anything can run *on*: a profile can name a
        text-to-speech or embedding model, and an agent on it fails on its first
        turn (#2487). Refused only where the catalogs know what the model is - an
        unknown model is allowed. Its fallbacks too: a provider failure hands the
        run to the next one in the chain, and a speech model there turns an outage
        into a run that fails anyway. The same for a profile with no key, the model
        itself (#2478) and its fallbacks: a run skips such a fallback, so the
        chain it was meant to be is shorter than it reads.
        """
        profile = await credential_repo.get_profile(
            self.db, profile_id, organization_id=ctx.organization_id
        )
        if profile is None:
            return ["The selected model profile no longer exists"]
        outputs = model_outputs(profile.provider, profile.model, base_url=profile.base_url)
        if not outputs.chat:
            return [not_chat_refusal(profile.label, profile.model, outputs)]
        if lacks_key(
            profile.provider,
            secret_id=profile.secret_id,
            base_url=profile.base_url,
            runs_without_key=profile.runs_without_key,
        ):
            # Its key was deleted from the vault, which leaves the profile in
            # place with nothing to authenticate with (#2478). Every run on it
            # would fail; say so here, while the author is looking.
            return [
                f"Model '{profile.label}' has no key - its key was deleted or never set. "
                "Choose a key for it in the model panel"
            ]
        problems: list[str] = []
        fallback_ids = [UUID(pid) for pid in profile.fallback_profile_ids[:MAX_FALLBACK_DEPTH]]
        fallbacks = await credential_repo.get_profiles_by_ids(
            self.db, fallback_ids, organization_id=ctx.organization_id
        )
        # In the chain's order. One that no longer exists is skipped at run
        # time, not refused here.
        for fallback in (fallbacks[pid] for pid in fallback_ids if pid in fallbacks):
            found = model_outputs(fallback.provider, fallback.model, base_url=fallback.base_url)
            if not found.chat:
                problems.append(
                    f"Model '{profile.label}' falls back to '{fallback.label}' "
                    f"({fallback.model}), which is {found.kind}, not a chat model - "
                    "remove it from the fallbacks"
                )
            elif lacks_key(
                fallback.provider,
                secret_id=fallback.secret_id,
                base_url=fallback.base_url,
                runs_without_key=fallback.runs_without_key,
            ):
                # A run would skip it, so an outage the chain exists for would
                # find nothing to fall back on - said here rather than then.
                problems.append(
                    f"Model '{profile.label}' falls back to '{fallback.label}', which has "
                    "no key - give it a key or remove it from the fallbacks"
                )
        return problems

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
        if not collection_ids:
            return []
        found = await knowledge_base_repo.get_by_ids(self.db, collection_ids)
        problems: list[str] = []
        for collection_id in collection_ids:
            collection = found.get(collection_id)
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
        registered = {definition.id for definition in all_capabilities()}
        for skill_id in skill_ids:
            skill = found.get(skill_id)
            reachable = skill is not None and await resolve_access(
                self.db, ctx, skill, Perm.SKILLS_VIEW, resource_type=SKILL
            )
            if not reachable:
                problems.append(f"Skill not found: {skill_id}")
                continue
            # Each skill is a deferred capability now, filed under its own name,
            # and the platform's capabilities are filed under theirs - in one
            # namespace. A skill called `planning` on an agent that also has the
            # `planning` capability is a duplicate id Pydantic AI refuses before
            # the first token, so the agent would publish and never run.
            if skill is not None and skill.name in registered:
                problems.append(
                    f"Skill '{skill.name}' has the name of a capability this platform "
                    "offers, and each skill is a capability now - rename the skill"
                )
        return problems

    async def _mcp_problems(self, ctx: AuthContext, refs: Sequence[McpServerRef]) -> list[str]:
        """Every way a set of MCP bindings can be unpublishable.

        An organization binding must name one of the organization's own
        connections - never a member's, because a published agent's reach
        cannot depend on whose session runs it. A personal binding must name a
        catalog service, once, under a prefix no organization binding of the
        same agent already uses: two servers under one prefix make Pydantic AI
        raise on the duplicate tool names and abort every turn. All of it asked
        here, where somebody can still change the binding, rather than at run
        time where the only options are to guess or to quietly drop a server.
        """
        problems: list[str] = []
        # What each binding would call its tools by, as the toolset builder derives
        # it - `notion-` and `notion` are one prefix. Paired with a label so the
        # same `prefix_collisions` the run uses catches a clash here, where somebody
        # can still fix it, rather than a server being dropped mid-turn (#1442).
        prefixed: list[tuple[str, str]] = []
        found = await mcp_connection_repo.get_org_scoped_by_ids(
            self.db,
            connection_ids=[ref.connection_id for ref in refs if isinstance(ref, OrgMcpServerRef)],
            organization_id=ctx.organization_id,
        )
        for ref in refs:
            if isinstance(ref, PlatformMcpServerRef):
                prefixed.append((PLATFORM_MCP_PREFIX, "this platform's own server"))
                continue
            if isinstance(ref, PersonalMcpServerRef):
                if mcp_catalog.get_entry(ref.catalog_key) is None:
                    problems.append(
                        f"No MCP catalog entry is called {ref.catalog_key!r}. A binding to each "
                        "person's own account names a catalog service, so their connections can "
                        "be matched to it."
                    )
                    continue
                prefixed.append((ref.catalog_key, f"each person's own {ref.catalog_key}"))
                continue
            connection = found.get(ref.connection_id)
            if (
                connection is not None
                and connection.visibility != Visibility.ORG.value
                and not await resolve_access(
                    self.db, ctx, connection, Perm.MCP_MANAGE, resource_type=MCP_CONNECTION
                )
            ):
                # Narrowed to groups the publisher is not in (#2072): binding it
                # would lend a department's server out, which is the publisher's
                # to do only once it is shared with them. Worded as a missing one,
                # so a guessed id maps nothing.
                problems.append(f"MCP server not found: {ref.connection_id}")
                continue
            if connection is None:
                # Says which of the two ways it can fail applies, because the
                # likely one - a personal connection picked in the Builder - is
                # not a missing row and "not found" would send the person
                # looking for something that is right in front of them.
                problems.append(
                    f"MCP server {ref.connection_id} is not shared with this organization. "
                    "An organization binding can only use connections the organization owns, "
                    "never a member's personal one - bind the service to each person's own "
                    "account instead if that is what you want."
                )
                continue
            prefixed.append((connection.name, f"the connection {connection.name!r}"))
        for prefix, holders in prefix_collisions(prefixed).items():
            problems.append(
                f"Two bindings would present their tools under the prefix {prefix!r}: "
                f"{' and '.join(holders)}. The model would see every tool twice, which "
                "aborts the turn - bind one of them, or rename the connection."
            )
        return problems

    async def _context_problems(self, ctx: AuthContext, context_ids: Sequence[UUID]) -> list[str]:
        """Context files the publisher cannot lend out.

        The same rule as a skill, for the same reason: a bound context file
        reaches every run of the agent - injected into its instructions or read
        through the capability's tool - so binding one shares its body. The
        publisher has to be able to reach it themselves. `CONTEXT_VIEW` through
        :func:`resolve_access`, so an explicit grant counts.

        "Not found" covers a missing id, another organization's id, and a row this
        publisher may not read, deliberately indistinguishably: files are bound by
        UUID from the API and from a hand-edited draft, so a refusal that read
        differently would map the organization's private context one guess at a
        time. One query for the whole list, because a run resolves them the same
        way and publish holds a transaction open.
        """
        if not context_ids:
            return []
        found = await context_repo.get_many(
            self.db, list(context_ids), organization_id=ctx.organization_id
        )
        problems: list[str] = []
        for context_id in context_ids:
            file = found.get(context_id)
            reachable = file is not None and await resolve_access(
                self.db, ctx, file, Perm.CONTEXT_VIEW, resource_type=CONTEXT
            )
            if not reachable:
                problems.append(f"Context file not found: {context_id}")
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
        if not requirement.accepts(secret.kind):
            return [
                f"Capability '{binding.id}' needs a {requirement.kind.value} secret, but "
                f"'{secret.name}' holds a {secret.kind}"
            ]
        # A sign-in is accepted for the coding agent only because Codex runs on
        # one; switched to Claude Code, it would refuse every task at run time.
        # Ahead of the purpose check, whose refusal would name the purpose rather
        # than say what a sign-in is.
        if (
            isinstance(config, CodingAgentConfig)
            and secret.kind == SecretKind.OPENAI_CODEX.value
            and config.harness != "codex"
        ):
            return [
                f"'{secret.name}' is a ChatGPT sign-in, which only Codex runs on - pick an "
                "Anthropic key or Claude subscription token for Claude Code"
            ]
        # Kind is not enough: an OpenAI key bound to a Google binding is the same
        # `api_key`, and would be sent in Google's auth header at every call. A
        # `custom` key - every key stored before purposes existed, and any for a
        # service the deployment does not name - is the author's word, as in the
        # Builder's picker (#2258, #2485).
        purposes = requirement.purposes_for(config)
        if purposes is not None and secret.purpose not in (*purposes, "custom"):
            return [
                f"Capability '{binding.id}' is set to use {' or '.join(purposes)}, but "
                f"'{secret.name}' is a key for {secret.purpose}"
            ]
        return []

    async def _observability_problems(self, ctx: AuthContext, spec: AgentSpec) -> list[str]:
        """Whether the token an agent redirects its traces with is publishable.

        `factory._instrument` says publishing is where a missing tracing secret
        is refused because a run is far too late: an unusable token there logs
        `agent_logfire_token_unavailable` and the agent runs untraced. So the
        token reference gets the same existence and tenant checks a capability's
        secret does, plus the `logfire` purpose gate `_check_logfire_secret`
        already applies on the environment path - a Tavily or OpenAI key passes
        a kind-only check (all three are `api_key`) and is then handed to Logfire
        as its token, exposing the credential to the wrong service. The purpose
        subsumes the kind: `_check_purpose` refuses a `logfire` secret that is
        not an `api_key` at creation. Miss and refusal read alike, so an id
        cannot enumerate the vault.
        """
        observability = spec.observability
        if observability is None or observability.token_secret_id is None:
            return []
        secret = await organization_secret_repo.get(
            self.db, observability.token_secret_id, organization_id=ctx.organization_id
        )
        if secret is None or not await resolve_access(
            self.db, ctx, secret, Perm.SECRETS_VIEW, resource_type=SECRET
        ):
            return [
                "The tracing token points at a secret this organization does not have: "
                f"{observability.token_secret_id}"
            ]
        if secret.purpose != "logfire":
            return [
                "The tracing token must be a Logfire key, but "
                f"'{secret.name}' is for {secret.purpose}"
            ]
        return []

    async def _speech_to_text_problems(
        self, ctx: AuthContext, override: SpeechToTextSpec | None
    ) -> list[str]:
        """Everything wrong with an agent's speech-to-text override.

        Here rather than on `SpeechToTextSpec` itself, because the Builder saves a
        draft on every change and a half-chosen pair - a provider picked, its model
        or its key not yet - is a draft somebody is in the middle of, not a
        mistake. Published, it is one: a provider with no model reads as
        configured and transcribes nothing, a model outside the catalog is
        refused by the provider while the person who sent the recording waits,
        and a pair with no key has nothing to pay with. All are caught while
        somebody is looking at the form, the same as every other reference a
        spec makes.

        The key follows the lending rule every key in a spec does - the
        publisher must be able to view it - plus the kind and purpose checks
        (`SpeechToTextSettingsService.key_problem`).
        """
        if override is None:
            return []
        problems: list[str] = []
        provider, model, secret_id = override.provider, override.model, override.secret_id
        if (provider is None) != (model is None):
            problems.append(
                "Speech to text needs a provider and a model together - choose both, or "
                "inherit the organization's"
            )
        elif provider is not None and model is not None:
            if not speech_to_text.is_offered(provider, model):
                problems.append(
                    f"Speech to text: '{model}' is not a transcription model this deployment "
                    f"offers for {provider}"
                )
            elif secret_id is None:
                problems.append(f"Speech to text: choose a key for {provider} to transcribe with")
            else:
                problem = await SpeechToTextSettingsService(self.db).key_problem(
                    secret_id, organization_id=ctx.organization_id, provider=provider, ctx=ctx
                )
                if problem is not None:
                    problems.append(f"Speech to text: {problem}")
        elif secret_id is not None:
            problems.append(
                "Speech to text: a key goes with a provider and a model - choose those, "
                "or clear the key to inherit the organization's"
            )
        if override.language is not None and override.language not in speech_to_text.LANGUAGES:
            problems.append(
                f"Speech to text: '{override.language}' is not a language transcription accepts"
            )
        return problems

    async def _voice_problems(self, ctx: AuthContext, voice: VoiceSpec | None) -> list[str]:
        """Everything wrong with an agent's Voice conversations section (#54).

        Refused at publish so a broken voice section is a red field, never a
        call that fails while somebody is talking: the pair is in the realtime
        catalog, the voice is one of the model's, the key passes the shared
        check (`provider_keys.key_problem`) with the kind its provider needs, and
        the language is one calls accept. The longest call's 50-minute ceiling is
        the field's own bound.
        """
        if voice is None:
            return []
        if voice.provider is None:
            return ["Voice: choose a provider and a model, or remove the voice section"]
        provider = realtime_models.by_provider(voice.provider)
        if provider is None:
            return [f"Voice: {voice.provider} cannot hold voice conversations on this deployment"]
        problems: list[str] = []
        catalog_model = voice.base_model if provider.deployment else voice.model
        if catalog_model is None:
            return [f"Voice: choose a model for {voice.provider}"]
        entry = realtime_models.offered(voice.provider, catalog_model)
        if entry is None:
            return [
                f"Voice: '{catalog_model}' is not a realtime model this deployment offers for {voice.provider}"
            ]
        if provider.deployment and not voice.deployment:
            problems.append(f"Voice: name the Azure deployment that runs {catalog_model}")
        if voice.voice is not None and voice.voice not in entry.voices:
            problems.append(f"Voice: {catalog_model} has no voice called '{voice.voice}'")
        if voice.secret_id is None:
            problems.append(f"Voice: choose a key for {voice.provider} to hold calls with")
        else:
            problem = await provider_keys.key_problem(
                self.db,
                voice.secret_id,
                organization_id=ctx.organization_id,
                provider=voice.provider,
                kind=provider.secret_kind,
                feature="voice conversations",
                ctx=ctx,
            )
            if problem is not None:
                problems.append(f"Voice: {problem}")
        if voice.language is not None and voice.language not in speech_to_text.LANGUAGES:
            problems.append(f"Voice: '{voice.language}' is not a language code calls accept")
        return problems

    async def _delegation_problems(
        self, ctx: AuthContext, spec: AgentSpec, *, agent_id: UUID | None
    ) -> _SpecProblems:
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
            if spec.subagents or spec.external_agents:
                # A pin nothing reads: the capability is what turns these into
                # tools, so without it they are configuration that reads as a
                # decision and has no effect - and the author who wired up three
                # delegates is the last person who would notice.
                return _SpecProblems(
                    [
                        "This agent names delegates, but its delegation capability is not "
                        "enabled - nothing would ever call them. Enable it, or remove them."
                    ]
                )
            return _SpecProblems()
        try:
            config = SubagentsConfig.model_validate(binding.config)
        except ValidationError:
            # `_binding_problems` has already reported the configuration itself.
            # A policy that does not parse says nothing further about the
            # specialists it would have carried, and guessing at half of one
            # would report problems against a shape nobody wrote.
            return _SpecProblems()

        problems = _SpecProblems()
        names: list[str] = []
        for specialist in config.inline:
            names.append(specialist.name)
            problems.merge(await self._specialist_problems(ctx, specialist))
        problems.add(_share_problems(spec, config))

        pins = await self._resolve_pins(ctx, spec.subagents)
        problems.add(pins.problems)
        # A delegate's handle is its row's slug; a specialist's is the name as
        # typed, which is already constrained to what a tool argument can carry.
        # Both are what the runtime hands the model, which is the only namespace
        # a collision can happen in.
        names.extend(pins.handles)
        remote = await self._external_agent_problems(ctx, spec)
        problems.add(remote[0])
        names.extend(remote[1])
        problems.add(_collision_problems(names))
        problems.add(
            await self._cycle_problems(ctx, pins.delegates, agent_id=agent_id, root_name=spec.name)
        )
        return problems

    async def _external_agent_problems(
        self, ctx: AuthContext, spec: AgentSpec
    ) -> tuple[list[str], list[str]]:
        """Remote agents named that this organization has not registered, and the
        handles of those it has - which share the namespace delegates are called in."""
        ids = [ref.external_agent_id for ref in spec.external_agents]
        found = await external_agent_repo.get_many(
            self.db, ids, organization_id=ctx.organization_id
        )
        problems = [
            f"Remote agent {ref_id} is not registered in this organization."
            for ref_id in ids
            if ref_id not in found
        ]
        # Its key is lent to every run, as a capability's is, so the publisher
        # must reach it - `_secret_problems` gives the reason, and a registration
        # is made by anybody who may edit agents, with a key of their own.
        for ref_id in ids:
            registered = found.get(ref_id)
            if registered is None or registered.secret_id is None:
                continue
            secret = await organization_secret_repo.get(
                self.db, registered.secret_id, organization_id=ctx.organization_id
            )
            if secret is None or not await resolve_access(
                self.db, ctx, secret, Perm.SECRETS_VIEW, resource_type=SECRET
            ):
                problems.append(
                    f"Remote agent '{registered.slug}' sends a key you cannot use; "
                    "ask whoever registered it to share the key, or register it with your own."
                )
        return problems, [found[ref_id].slug for ref_id in ids if ref_id in found]

    async def _specialist_problems(
        self, ctx: AuthContext, specialist: SpecialistSpec
    ) -> _SpecProblems:
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
        problems = _SpecProblems()
        for binding in specialist.capabilities:
            problems.merge(await self._binding_problems(ctx, binding))
        problems.add(await self._collection_problems(ctx, specialist.collection_ids))
        problems.add(await self._skill_problems(ctx, specialist.skill_ids))
        problems.add(await self._context_problems(ctx, specialist.context_ids))
        # A specialist naming no profile runs on the parent's, which publish has
        # already checked - so only a profile it *did* name is a reference that
        # can be broken, or borrowed from another organization.
        if specialist.model_profile_id is not None:
            problems.add(await self.model_profile_problems(ctx, specialist.model_profile_id))
        # Its instructions are filled the way the parent's are, so a typo in a
        # variable is refused here too rather than sent to the model as braces.
        problems.merge(_variable_problems(specialist.to_agent_spec(fallback_model_profile_id=None)))
        return problems.within_specialist(specialist.name)

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
        found = await agent_repo.get_many(
            self.db, [ref.agent_id for ref in refs], organization_id=ctx.organization_id
        )
        for ref in refs:
            delegate = found.get(ref.agent_id)
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
            version=version.version,
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
        """Validate and freeze one locked draft; saves and promotions wait for its commit.

        The agent lock also serializes MAX(version)+1 allocation with rollback.
        A save waiting behind this publication retains its newer draft afterwards.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH, for_update=True)
        spec = AgentSpec.model_validate(agent.draft_spec)
        await self.validate_spec(ctx, spec, agent_id=agent.id)

        # Publish is where the spec is confirmed against this deployment's own
        # registry and models, so the frozen copy carries this deployment's spec
        # version - not whatever an imported draft claimed. Otherwise the number
        # is write-only: a `spec_version: 3` YAML publishes carrying constructs
        # this code understands and stays labelled 3.
        spec.spec_version = SPEC_VERSION
        frozen = spec.model_dump(mode="json")

        number = await agent_repo.next_version_number(self.db, agent_id=agent.id)
        version = await agent_repo.create_version(
            self.db,
            agent_id=agent.id,
            organization_id=ctx.organization_id,
            version=number,
            spec=frozen,
            note=note,
            published_by_user_id=ctx.user_id,
        )
        # The draft takes the stamped copy too: left at the number it was saved
        # with, a draft that is exactly what was just published reads as
        # "differs from" it, and stays that way until somebody edits it.
        await agent_repo.update(
            self.db,
            agent=agent,
            update_data={"status": AgentStatus.PUBLISHED.value, "draft_spec": frozen},
        )
        # `current_version_id` is the default environment's pointer, so the step
        # that moves environments is the step that moves it - see below.
        await self._move_environments_that_follow(ctx, agent=agent, version=version)
        await self.withdraw_creator_consent(ctx, agent)
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

    async def withdraw_creator_consent(self, ctx: AuthContext, agent: Agent) -> None:
        """Switch "run as me" off on the triggers somebody else made, as the code they run changes.

        A creator who let a trigger act as them agreed to what the agent did then.
        A new version put in front of their trigger by somebody else - a publish
        an environment follows, a promotion, a rollback - could read their mailbox
        with their connections, so their consent does not carry over to it; their
        own publishes keep it (#2027) - in person only. Through one of their API
        keys, or by an administrator impersonating them, it is somebody else's
        publish: the rule `agent_trigger._acts_as_themselves` sets for granting
        the consent holds for keeping it.
        """
        in_person = ctx.api_key_id is None and current_impersonator() is None
        withdrawn = await agent_trigger_repo.withdraw_creator_consent(
            self.db, agent_id=agent.id, kept_for=ctx.user_id if in_person else None
        )
        if withdrawn:
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="agent_trigger.creator_consent_withdrawn",
                target_type="agent",
                target_id=str(agent.id),
                details={"triggers": withdrawn},
            )

    async def _move_environments_that_follow(
        self, ctx: AuthContext, *, agent: Agent, version: AgentVersion
    ) -> None:
        """Repoint the environments that asked to follow publishes, and no others.

        **Publishing mints a version; putting it somewhere is a separate
        decision.** This used to repoint the default whatever it was, so
        "publish" and "deploy to production" were one click with nothing on
        screen saying so - an author fixing a prompt changed what the live Slack
        bot answered with, in the same action.

        An environment in `tracks_latest` mode is the exception it asked to be:
        a `dev` somebody is iterating in follows every publish, which is the
        whole reason that mode exists.

        The **first** publish is different, and has to be: an agent with no
        environment has nowhere to run at all, so it gets its `production`
        default here, on the version that just appeared - and **following
        publishes**. With one environment there is nothing to promote between,
        and pinning it made every change a publish and then a promotion before it
        could be tried. Somebody who adds a `dev` or a `staging` pins
        `production`, and from then on a publish leaves it where it is.

        `Agent.current_version_id` mirrors the default environment, which is what
        a surface naming no environment resolves through - so it moves when that
        environment moves, and a publish that moves nothing moves it neither.
        """
        default = await agent_environment_repo.get_default_for_agent(self.db, agent_id=agent.id)
        if default is None:
            default = await agent_environment_repo.create(
                self.db,
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="production",
                version_id=version.id,
                is_default=True,
                tracks_latest=True,
                created_by_user_id=ctx.user_id,
            )
        else:
            for environment in await agent_environment_repo.following_latest(
                self.db, agent_id=agent.id, organization_id=ctx.organization_id
            ):
                await agent_environment_repo.update(
                    self.db, environment=environment, update_data={"version_id": version.id}
                )
                if environment.id == default.id:
                    default = environment
        await agent_repo.update(
            self.db, agent=agent, update_data={"current_version_id": default.version_id}
        )

    async def rollback(
        self, ctx: AuthContext, agent_id: UUID, *, to_version_id: UUID
    ) -> AgentVersion:
        """Republish an earlier spec as a new version.

        History stays linear: the timeline shows that a rollback happened rather
        than pretending the bad version never existed.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH, for_update=True)
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
                "status": AgentStatus.PUBLISHED.value,
                "draft_spec": source.spec,
            },
        )
        # A rollback is a publish of an older spec, so it lands the same way: the
        # version exists, and what serves it is a promotion. Putting the old
        # version back in front of people directly is one click on the history
        # row - promote - rather than two here.
        await self._move_environments_that_follow(ctx, agent=agent, version=version)
        await self.withdraw_creator_consent(ctx, agent)
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
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        if await organization_assistant_repo.for_agent(self.db, agent.id) is not None:
            # Archived, it would still read as ready in the corner and refuse every
            # run; switching it off is the way to retire it.
            raise BadRequestError(
                message="Switch the AI Architect off in Settings instead of archiving it",
                details={"agent_id": agent.id},
            )
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
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        if agent.status != AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is not archived",
                details={"agent_id": str(agent.id), "status": agent.status},
            )
        # Restoring is a transition into the counted state, since the ceiling counts
        # live agents only: without this an organization at its limit archives one,
        # creates a replacement and restores what it archived.
        await self._refuse_past_the_ceiling(ctx)
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
        # Stored under a suffix from the validated type, not the caller's
        # filename, so a valid image is renderable whatever it was named (#702).
        path = await storage.save(
            f"avatars/agents/{agent.id}", avatar_filename(content_type), file_data
        )
        return await agent_repo.update(self.db, agent=agent, update_data={"avatar_url": path})

    async def set_avatar_color(
        self, ctx: AuthContext, agent_id: UUID, *, color: int | None
    ) -> Agent:
        """Choose the agent's default-avatar colour, or null to reset to auto.

        A column like the picture, not the spec: editing it takes the same
        access check (`AGENTS_EDIT` on this agent) but does not touch a version.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        return await agent_repo.update(self.db, agent=agent, update_data={"avatar_color": color})

    async def set_metadata(
        self, ctx: AuthContext, agent_id: UUID, *, categories: list[str], tags: list[str]
    ) -> Agent:
        """Set the agent's discovery categories and tags, or clear them with [].

        Record metadata like the avatar, not the spec: editing takes the same
        per-resource access check (`AGENTS_EDIT`, grant-aware through `self.get`,
        so a Viewer holding an explicit edit grant may retag that one agent) but
        touches no version. The lists arrive already folded by the schema
        validator, so this only persists them.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        return await agent_repo.update(
            self.db, agent=agent, update_data={"categories": categories, "tags": tags}
        )

    async def set_a2a(self, ctx: AuthContext, agent_id: UUID, *, enabled: bool) -> Agent:
        """Serve this agent over A2A, or stop (#2092).

        A publishing decision rather than an edit: turning it on makes the agent's
        name and description readable by anybody who has the card's address, and
        reachable by every key and OAuth grant of the organization allowed to run
        it. So it takes `AGENTS_PUBLISH`, grant-aware through `self.get`, and an
        agent with no published version cannot be served - it has nothing to run.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_PUBLISH)
        if enabled and agent.current_version_id is None:
            raise BadRequestError(
                message="Publish the agent before serving it over A2A",
                details={"agent_id": agent.id},
            )
        updated = await agent_repo.update(
            self.db, agent=agent, update_data={"a2a_enabled": enabled}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="agent.a2a_served" if enabled else "agent.a2a_withdrawn",
            target_type="agent",
            target_id=str(agent.id),
        )
        return updated

    async def avatar_path(self, ctx: AuthContext, agent_id: UUID) -> str:
        """The storage path of the agent's picture, for the route that streams it.

        The path the storage backend wrote, not a path on this host: an object
        store has no second kind, and the route hands this to the one place that
        knows how to turn either into a response (#1423).

        Reading the picture goes through the same access check as reading the
        agent: an avatar is not public just because it is an image, and an
        unguarded path would say which agent ids exist.

        Raises:
            NotFoundError: If the agent has no avatar, or the stored file is
                gone - indistinguishable to a caller, and deliberately so.
        """
        agent = await self.get(ctx, agent_id)
        if not agent.avatar_url or not await get_file_storage().exists(agent.avatar_url):
            raise NotFoundError(
                message="This agent has no avatar", details={"agent_id": str(agent_id)}
            )
        return agent.avatar_url

    async def delete(self, ctx: AuthContext, agent_id: UUID, *, draft_only: bool = False) -> None:
        """Permanently remove an agent, its versions and its shares.

        `draft_only` is the undo of a draft made by mistake: the agent must be the
        caller's and never published, read from the row locked for this
        transaction - a publish committed since the caller looked is seen, and
        one starting now waits for the delete.

        Raises:
            BadRequestError: `draft_only`, and the agent is somebody else's or was
                published.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        if draft_only and (
            agent.owner_user_id != ctx.subject_id or agent.current_version_id is not None
        ):
            raise BadRequestError(
                message="Only a never-published draft you created can be undone",
                details={"agent_id": agent.id},
            )
        # The agent's triggers go with it by CASCADE, which would silently discard
        # the provider webhook ids their auto-registered hooks are removable by -
        # so the provider side is swept first, best-effort. Imported locally:
        # the trigger service imports this module at module scope.
        from app.services.agent_trigger import AgentTriggerService

        await AgentTriggerService(self.db).deregister_agent_webhooks(ctx, agent.id)
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

    async def list_versions(
        self, ctx: AuthContext, agent_id: UUID, *, skip: int = 0, limit: int = 25
    ) -> tuple[list[AgentVersionRead], int]:
        """One page of the timeline, with who published each entry, and the total.

        The author is resolved here rather than left as an id: "who changed
        this" is the whole reason a history is read, and a column of uuids
        answers it with another question. One lookup for the page, not one per
        row.

        The total is counted rather than taken from the page. It used to be the
        page's own length against a listing capped at fifty, so an agent
        published sixty times reported fifty versions and the ten oldest could
        not be reached at all - including whichever one an environment was still
        pinned to.
        """
        agent = await self.get(ctx, agent_id)
        versions = await agent_repo.list_versions(
            self.db, agent_id=agent.id, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        total = await agent_repo.count_versions(
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
        ], total

    async def delegation_tree(self, ctx: AuthContext, agent_id: UUID) -> DelegationTree:
        """The delegation tree under this agent's draft, in one response (#276).

        The map used to walk this one hop at a time - a delegate's page, then its
        delegate's page - so the whole tree was N requests and N permission
        checks spread over N clicks. This is the server-side answer: one walk,
        the same pin resolution publish uses, bounded the same two ways the
        cycle check is (nothing past :data:`_MAX_DELEGATION_NODES` reads, and a
        pin that returns to its own branch is named as a cycle rather than
        followed).

        Depth is the *runtime* bound, not the roster's. A delegate gets the
        lower of its own `max_depth` and what this branch has left, exactly as
        `subagent_runtime` hands it down, so the tree shows what a run from this
        root can actually reach and marks the rest `truncated` rather than
        drawing levels that would never execute.

        Each delegate is access-checked against the *caller*, not the publisher:
        a pin to an agent this caller may not see comes back `restricted`, with
        no name and no children, indistinguishable from a pin to an agent that
        does not exist - the same no-probing rule `_resolve_pins` applies at
        publish. A delegate somebody has since archived comes back `archived`
        and unexpanded, because a run that reaches that hop is refused.
        """
        agent = await self.get(ctx, agent_id)
        spec = AgentSpec.model_validate(agent.draft_spec)
        config = _subagents_config(spec)
        walk = _TreeWalk()
        nodes = await self._tree_level(
            ctx,
            spec,
            budget=config.max_depth if config else 0,
            ancestors=frozenset({agent.id}),
            walk=walk,
        )
        return DelegationTree(truncated=walk.capped, nodes=nodes)

    async def _tree_level(
        self,
        ctx: AuthContext,
        spec: AgentSpec,
        *,
        budget: int,
        ancestors: frozenset[UUID],
        walk: _TreeWalk,
    ) -> list[DelegationTreeNode]:
        """One spec's roster as tree nodes: its pins, then its inline specialists."""
        nodes: list[DelegationTreeNode] = []
        for index, ref in enumerate(spec.subagents):
            if walk.count >= _MAX_DELEGATION_NODES:
                walk.capped = True
                break
            nodes.append(
                await self._tree_delegate(
                    ctx, ref, index=index, budget=budget, ancestors=ancestors, walk=walk
                )
            )
        config = _subagents_config(spec)
        for index, specialist in enumerate(config.inline if config else []):
            nodes.append(
                DelegationTreeNode(
                    key=f"specialist:{index}",
                    kind="specialist",
                    status="ok",
                    name=specialist.name,
                    mode=specialist.preferred_mode,
                )
            )
        return nodes

    async def _tree_delegate(
        self,
        ctx: AuthContext,
        ref: SubagentRef,
        *,
        index: int,
        budget: int,
        ancestors: frozenset[UUID],
        walk: _TreeWalk,
    ) -> DelegationTreeNode:
        """One pin as a tree node, expanded only as far as a run could follow it."""
        walk.count += 1
        key = f"delegate:{ref.agent_id}:{index}"
        row = await self._tree_row(ctx, ref.agent_id, walk)
        if row is None:
            return DelegationTreeNode(
                key=key,
                kind="delegate",
                status="restricted",
                agent_id=ref.agent_id,
                mode=ref.preferred_mode,
            )
        if ref.agent_id in ancestors:
            return DelegationTreeNode(
                key=key,
                kind="delegate",
                status="cycle",
                agent_id=ref.agent_id,
                name=row.name,
                mode=ref.preferred_mode,
            )
        # Ordered as `_resolve_delegate` orders its refusals: a run refuses the
        # loop before it has looked at the delegate at all, so a pin that is both
        # a cycle and archived reads as the cycle here too.
        if row.status == AgentStatus.ARCHIVED.value:
            return DelegationTreeNode(
                key=key,
                kind="delegate",
                status="archived",
                agent_id=ref.agent_id,
                name=row.name,
                mode=ref.preferred_mode,
            )
        pinned = await self._tree_pin(ctx, ref, walk)
        if pinned is None:
            return DelegationTreeNode(
                key=key,
                kind="delegate",
                status="unpinned",
                agent_id=ref.agent_id,
                name=row.name,
                mode=ref.preferred_mode,
            )
        config = _subagents_config(pinned.spec)
        roster = len(pinned.spec.subagents) + len(config.inline if config else [])
        remaining = min(budget - 1, config.max_depth) if config else 0
        children: list[DelegationTreeNode] = []
        truncated = False
        if roster:
            if remaining >= 1:
                children = await self._tree_level(
                    ctx,
                    pinned.spec,
                    budget=remaining,
                    ancestors=ancestors | {ref.agent_id},
                    walk=walk,
                )
            else:
                truncated = True
        return DelegationTreeNode(
            key=key,
            kind="delegate",
            status="ok",
            agent_id=ref.agent_id,
            name=row.name,
            mode=ref.preferred_mode,
            pinned_version=pinned.version,
            stale=row.current_version_id != pinned.version_id,
            truncated=truncated,
            children=children,
        )

    async def _tree_row(self, ctx: AuthContext, agent_id: UUID, walk: _TreeWalk) -> Agent | None:
        """The delegate's row, when this caller may see it - cached per walk.

        A row the caller may not view is answered as absent, so the two are
        indistinguishable downstream by construction, not by discipline.
        """
        if agent_id not in walk.rows:
            row = await agent_repo.get(self.db, agent_id, organization_id=ctx.organization_id)
            if row is not None and not await resolve_access(
                self.db, ctx, row, Perm.AGENTS_VIEW, resource_type=AGENT
            ):
                row = None
            walk.rows[agent_id] = row
        return walk.rows[agent_id]

    async def _tree_pin(
        self, ctx: AuthContext, ref: SubagentRef, walk: _TreeWalk
    ) -> _PinnedDelegate | None:
        """`_resolve_pin`, cached per walk so a diamond costs one version read."""
        cache_key = (ref.agent_id, ref.agent_version_id)
        if cache_key not in walk.pins:
            walk.pins[cache_key] = await self._resolve_pin(ctx, ref)
        return walk.pins[cache_key]

    async def ceiling(self, ctx: AuthContext) -> AgentCeiling:
        """The organization's agent limit, and whether a create would be refused for it.

        Counted as `_refuse_past_the_ceiling` counts, but without its lock - a
        forecast; the refusal stays the guarantee. The route gates this on
        `agents:edit`: a caller with no create has nothing to forecast.

        The count is of every agent in the organization, so `held` goes only to
        a caller whose `agents:view` already reaches all of them. Given to a
        Member, who sees their own and what was shared, it minus their listing's
        `total` would be how many agents are hidden from them, and polling it
        would show when somebody else creates one. They get `at_limit` alone,
        which a refused create would tell them anyway: at the limit the count is
        the limit.
        """
        limit = (await DeploymentSettingsService(self.db).limits()).agents_per_organization
        if limit is None:
            return AgentCeiling(limit=None, held=None, at_limit=False)
        held = await agent_repo.count_for_organization(self.db, organization_id=ctx.organization_id)
        sees_every_agent = ctx.scope_for(Perm.AGENTS_VIEW) is Scope.ALL
        return AgentCeiling(
            limit=limit, held=held if sees_every_agent else None, at_limit=held >= limit
        )

    async def _refuse_past_the_ceiling(self, ctx: AuthContext) -> None:
        """Refuse a transition that would put this organization over the limit.

        Archived agents are not counted: archiving is how an agent is retired,
        and a ceiling a retired agent went on occupying would make the only way
        back under it a delete - which takes the version history and the run
        attribution with it.

        Which is exactly why **`unarchive` calls this too**. Counting only the live
        rows means restoring one is a transition *into* the counted state, and a
        ceiling enforced on creates alone is one an organization walks past by
        archiving an agent, creating a replacement and restoring what it archived.

        The lock is what makes the count mean anything: read and acted on without
        one, two creates both pass it and both insert, so the ceiling is exceeded
        deterministically by clicking twice - and no constraint can say "at most
        five rows like this". Taken only where a limit exists, and released by the
        transaction whichever way it ends.
        """
        limit = (await DeploymentSettingsService(self.db).limits()).agents_per_organization
        if limit is None:
            return
        await hold_subject(self.db, LockScope.AGENTS_PER_ORGANIZATION, ctx.organization_id)
        held = await agent_repo.count_for_organization(self.db, organization_id=ctx.organization_id)
        if held >= limit:
            raise BadRequestError(
                message=(
                    f"This deployment allows {limit} agents per organization, and this one "
                    f"has {held}. Ask an administrator to raise the limit, or archive an "
                    "agent you no longer run."
                ),
                details={"limit": limit, "held": held},
            )

    async def with_assistant_guidance(self, agent: Agent, spec: AgentSpec) -> AgentSpec:
        """Add current Projects guidance only to the registered Architect's runtime copy.

        Existing installations keep their customized stored specs. Other agents
        and external MCP clients keep their own workflow, even with platform tools.
        """
        platform = next(
            (ref for ref in spec.mcp_servers if isinstance(ref, PlatformMcpServerRef)), None
        )
        if platform is None:
            return spec
        required = {"list_projects", "get_project", "create_project"}
        if platform.allowed_tools is not None and not required.issubset(platform.allowed_tools):
            return spec
        assistant = await organization_assistant_repo.for_agent(self.db, agent.id)
        if assistant is None or assistant.organization_id != agent.organization_id:
            return spec
        guidance = (
            (agent_templates.TEMPLATES_ROOT / "general/platform-assistant/PROJECTS.md")
            .read_text()
            .strip()
        )
        if guidance in spec.instructions:
            return spec
        return spec.model_copy(update={"instructions": f"{spec.instructions}\n\n{guidance}"})

    async def refuse_a_switched_off_assistant(self, agent_id: UUID) -> None:
        """Refuse running - or continuing a run of - an assistant somebody switched off (#2063).

        The organization's AI Architect is otherwise an ordinary agent: who may
        run it is `agents:run`, as for any other.

        Raises:
            BadRequestError: The assistant has been switched off.
        """
        assistant = await organization_assistant_repo.for_agent(self.db, agent_id)
        if assistant is not None and not assistant.enabled:
            raise BadRequestError(
                message="The assistant is switched off in this organization",
                details={"agent_id": str(agent_id)},
            )

    async def get_draft_spec(self, ctx: AuthContext, agent_id: UUID) -> tuple[Agent, AgentSpec]:
        """The draft as it stands, for the Builder's test panel to run (#2074).

        Whoever may edit the agent may try what they are editing - nothing is
        published, and the run is recorded as a test. The draft is checked the
        way a publish checks it, so a test refuses what a publish would, with the
        same list of problems, rather than failing halfway through a turn.

        Raises:
            NotFoundError: If the caller may not edit this agent.
            BadRequestError: If it is archived, or the draft would not publish.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT)
        if agent.status == AgentStatus.ARCHIVED.value:
            raise BadRequestError(
                message=f"Agent '{agent.name}' is archived", details={"agent_id": str(agent.id)}
            )
        spec = AgentSpec.model_validate(agent.draft_spec)
        await self.validate_spec(ctx, spec, agent_id=agent.id)
        return agent, spec

    async def enable_capability(
        self, ctx: AuthContext, agent_id: UUID, capability_id: str
    ) -> CapabilityEnabled:
        """Switch a capability on from the card an agent showed for it (#2301).

        Bound as the starter agent binds it, where it does, so it arrives
        configured as the Toolbox would recommend. Checked the way a publish
        checks it before anything is written, so a capability that needs a key
        nobody stored is refused with the reason and the draft is left alone.
        Published only when the draft was exactly the published version and the
        caller may publish: a draft holding somebody's unfinished edits is not
        made live as a side effect of a click in a chat.

        Raises:
            NotFoundError: If the caller may not edit this agent.
            BadRequestError: If no agent may bind such a capability, or the
                agent would not publish with it.
        """
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_EDIT, for_update=True)
        definition = get_capability(capability_id)
        if not definition.selectable:
            raise refused_field(
                "capability_id", f"{definition.name} is not something an agent can be given"
            )
        draft = AgentSpec.model_validate(agent.draft_spec)
        unchanged = await self._is_published_as_is(agent)
        recommended = agent_templates.starter_capabilities().get(
            capability_id, {"id": capability_id}
        )
        # A binding switched off keeps its place and its config; only a missing one is added.
        if any(binding.id == capability_id for binding in draft.capabilities):
            bindings = [
                binding.model_copy(update={"enabled": True})
                if binding.id == capability_id
                else binding
                for binding in draft.capabilities
            ]
        else:
            bindings = [*draft.capabilities, CapabilityBindingSpec.model_validate(recommended)]
        spec = draft.model_copy(update={"capabilities": bindings})
        await self.validate_spec(ctx, spec, agent_id=agent.id)
        await self.save_draft(ctx, agent.id, spec)
        may_publish = await resolve_access(
            self.db, ctx, agent, Perm.AGENTS_PUBLISH, resource_type=AGENT
        )
        if not (unchanged and may_publish):
            return CapabilityEnabled(published=False)
        await self.publish(ctx, agent.id, note=f"Switched on {definition.name}")
        return CapabilityEnabled(published=True)

    async def _is_published_as_is(self, agent: Agent) -> bool:
        """Whether the draft is exactly the version that runs - nothing unpublished in it."""
        if agent.current_version_id is None:
            return False
        version = await agent_repo.get_version(
            self.db, agent.current_version_id, organization_id=agent.organization_id
        )
        return version is not None and version.spec == agent.draft_spec

    async def ask_for_capability(
        self, ctx: AuthContext, agent_id: UUID, capability_id: str, *, reason: str
    ) -> None:
        """Ask an agent's owner to switch a capability on, from its card (#2301).

        Anyone who may talk to the agent may ask; the owner decides. The ask is
        the person's own words beside the capability's name, and the owner is
        told once however often it is clicked.

        Raises:
            AuthorizationError: If no person is signed in to be named as asking.
            NotFoundError: If the caller may not run this agent.
            BadRequestError: If no agent may bind such a capability.
        """
        if ctx.user_id is None:
            raise AuthorizationError(
                message="Only a signed-in person can ask an agent's owner",
                details={"agent_id": agent_id},
            )
        agent = await self.get(ctx, agent_id, perm=Perm.AGENTS_RUN)
        definition = get_capability(capability_id)
        if not definition.selectable:
            raise refused_field(
                "capability_id", f"{definition.name} is not something an agent can be given"
            )
        requester = await user_repo.get_by_id(self.db, ctx.user_id)
        name = (requester.full_name or requester.email) if requester is not None else "Somebody"
        await NotificationService(self.db).capability_requested(
            agent=agent,
            capability_name=definition.name,
            capability_id=definition.id,
            reason=reason,
            requester_id=ctx.user_id,
            requester_name=name,
        )

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
        await self.refuse_a_switched_off_assistant(agent.id)
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
