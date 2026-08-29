"""The agent spec - the contract between the Builder and the runtime.

An agent is data, not code. This module defines exactly what that data is, and
it is the most load-bearing type in the platform: the Builder edits it, the
database versions it, the factory instantiates it, and a client exports it to
their own git repository as YAML. Everything else can be rewritten; changing
this shape breaks stored agents.

Design rules that follow from that, and are worth keeping:

*References, never values.* A spec names a model profile, a collection, a tool
id - it never embeds a model string, a connection string, or (least of all) a
secret. That is what makes a spec safe to commit to a client's repository and
what lets an organization rotate a key without touching a single agent.

*Additive evolution.* New fields get defaults so an agent published today still
loads after an upgrade. Removing or renaming a field is a migration, not an
edit.

*Validated at publish.* A spec that references a missing tool or an ungranted
scope is rejected when saved, so a broken agent never reaches a conversation.
"""

from __future__ import annotations

import logging
from collections import Counter
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from app.agents.capabilities import CapabilityBinding, ToolOverride

logger = logging.getLogger(__name__)

# 8 adds `observability.organization` and `observability.project` - where an
# agent's traces can be *read*, which a write token does not say. Both optional
# with a default, so every stored document keeps loading unchanged and there is no
# migration to write: this is the free half of the table in the `agent-spec`
# skill, and the bump is here so a reader can tell when the field appeared.
#
# 9 adds `context_ids` - context files the agent injects into its instructions or
# exposes through the `context` capability's tool. Same free half of the table:
# a list with an empty default, so every stored spec loads unchanged.
#
# 10 replaces `mcp_server_ids` with `mcp_servers`, a list of typed references,
# because the binding grew a policy: whether a run may reach the same service
# through the *runner's own* account instead of the organization's. A bare id
# had nowhere to carry that, and a second parallel list of flagged ids is two
# lists that drift.
SPEC_VERSION = 10

ApprovalMode = Literal["default", "required", "never"]

_LEGACY_RENAME_CAPABILITY = "knowledge"
_LEGACY_RENAME_TOOL = "search_documents"
_THINKING_CAPABILITY = "thinking"
_THINKING_SETTING = "thinking"
_MODEL_SETTINGS_WITHDRAWN = frozenset(
    {
        "extra_body",
        "extra_headers",
        "logit_bias",
        "frequency_penalty",
        "presence_penalty",
        "top_k",
        "seed",
        "stop_sequences",
        "service_tier",
        "tool_choice",
        _THINKING_SETTING,
    }
)


class CapabilityBindingSpec(BaseModel):
    """One capability as this agent uses it.

    A capability is the unit worth switching on or off, and it covers things
    that are not tools at all, like a guardrail or a compaction strategy.

    Two things are decided finer than that, and both key on a tool's stable id.
    A capability that reads and writes is two decisions wearing one name, so
    `tool_approval` overrides `approval` for one tool - approve the write,
    leave the read alone. And what the model *reads* about a tool is the
    strongest prompt in the product, so `tool_overrides` reworks its name and
    description for this agent without forking the capability.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Registry id of the capability - stable across renames")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Validated against the capability's config schema at publish time",
    )
    approval: ApprovalMode = Field(
        default="default",
        description=(
            "The default for every tool this capability contributes; "
            "'default' follows the capability's side_effecting flag"
        ),
    )
    tool_approval: dict[str, ApprovalMode] = Field(
        default_factory=dict,
        description=(
            "Per-tool overrides on top of 'approval', keyed by the tool's "
            "stable id - not the name the model sees, which a binding may "
            "rename. An id no such capability exposes is refused at publish."
        ),
    )
    tool_overrides: dict[str, ToolOverride] = Field(
        default_factory=dict,
        description=(
            "Per-tool name and description overrides, keyed by the tool's "
            "stable id. An id no such capability exposes is refused at publish, "
            "and so is a name a model could not call."
        ),
    )
    secret_id: UUID | None = Field(
        default=None,
        description=(
            "Which of the organization's secrets satisfies this capability's "
            "requirement. An id, never a value - a spec is exported to a client's "
            "git repository. Refused at publish if it does not exist, is the "
            "wrong kind, or belongs to another organization."
        ),
    )
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _fold_the_knowledge_capabilitys_own_rename(cls, data: Any) -> Any:
        """Move a version-3 knowledge rename into the general field.

        `knowledge` used to carry `tool_name` and `tool_description` in
        its own config - a mechanism one capability invented for itself, which
        approval could not see through. Its schema no longer has those keys, and
        a Pydantic model ignores what it does not declare: without this, every
        agent published against version 3 would quietly lose its rename, and the
        model would start seeing a tool the instructions never mention.

        An override the spec states explicitly wins, so re-reading a spec this
        already migrated changes nothing.
        """
        if not isinstance(data, dict) or data.get("id") != _LEGACY_RENAME_CAPABILITY:
            return data
        config = data.get("config")
        if not isinstance(config, dict):
            return data
        legacy = {
            "name": config.get("tool_name"),
            "description": config.get("tool_description"),
        }
        if not any(legacy.values()):
            return data
        return {
            **data,
            "config": {
                key: value
                for key, value in config.items()
                if key not in ("tool_name", "tool_description")
            },
            "tool_overrides": {
                _LEGACY_RENAME_TOOL: legacy,
                **(data.get("tool_overrides") or {}),
            },
        }

    def to_binding(self) -> CapabilityBinding:
        return CapabilityBinding(
            capability_id=self.id,
            config=self.config,
            tool_overrides=self.tool_overrides,
            secret_id=self.secret_id,
            enabled=self.enabled,
        )


class BudgetSpec(BaseModel):
    """Spending limit for this agent.

    One monthly cap, metered against this agent's own runs. The platform has
    exactly two budget levels - the agent's and the organization's - and this
    is the agent's half.
    """

    model_config = ConfigDict(extra="forbid")

    monthly_usd: float | None = Field(default=None, gt=0)


class AlertAudience(StrEnum):
    """Who an agent's alert reaches.

    A list of these rather than one value, because the real answers are unions:
    "the person who asked, and the admins" is the sensible default for an
    approval and cannot be said with a single choice.

    Deliberately roles rather than addresses, with `CHOSEN` as the one escape
    hatch. An audience of user ids goes stale the moment somebody leaves, and a
    spec is exported to a client's repository - `ADMINS` still means the right
    people after a reorganisation, and it means them in whichever organization
    the spec is imported into.
    """

    ADMINS = "admins"
    """The organization's owners and admins, plus the deployment's app admins."""

    OWNER = "owner"
    """Whoever owns the agent - the person who would fix its configuration."""

    INITIATOR = "initiator"
    """Whoever started the run. Nobody, for a run no person began."""

    CHOSEN = "chosen"
    """Exactly the members named in `user_ids`."""


class AlertSpec(BaseModel):
    """Whether one kind of alert is sent for this agent, and to whom.

    Every audience is resolved and the addresses are merged, so naming the same
    person twice mails them once. Each recipient's own
    `/settings/notifications` switch is applied last and can only ever remove
    them: an agent cannot conscript somebody into an inbox they opted out of.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    to: list[AlertAudience] = Field(default_factory=lambda: [AlertAudience.ADMINS])
    user_ids: list[UUID] = Field(
        default_factory=list,
        description="Members to mail when `to` includes `chosen`; ignored otherwise",
    )

    @model_validator(mode="after")
    def _audience_and_list_must_agree(self) -> AlertSpec:
        """Refuse the two shapes that silently mail nobody, or nobody extra.

        Both are configurations somebody would write believing they had set up
        an alert. `chosen` with an empty list is an audience of nobody; ids
        without `chosen` are ids nothing reads. Neither is worth a warning in a
        log that no author of a spec will ever see.
        """
        if AlertAudience.CHOSEN in self.to and not self.user_ids:
            raise ValueError("`chosen` needs at least one member in `user_ids`")
        if self.user_ids and AlertAudience.CHOSEN not in self.to:
            raise ValueError("`user_ids` is only read when `to` includes `chosen`")
        if self.enabled and not self.to:
            raise ValueError("An enabled alert needs at least one audience in `to`")
        return self


def _initiator_and_admins() -> list[AlertAudience]:
    """The approval default.

    The initiator because they are waiting on it, and the admins because a run
    a schedule or a channel started has no initiator - and an approval queue
    nobody is told about is a run that sits parked until somebody notices.
    """
    return [AlertAudience.INITIATOR, AlertAudience.ADMINS]


def _admins_and_owner() -> list[AlertAudience]:
    """The budget default: the people who pay, and the person who can fix it."""
    return [AlertAudience.ADMINS, AlertAudience.OWNER]


class NotificationSpec(BaseModel):
    """Which of this agent's alerts are sent, and who hears each one.

    Per agent because the alerts are about an agent. A deployment-wide switch
    made the noisy agent and the one nobody may miss the same setting, so the
    only way to quieten the first was to go deaf to the second.

    What is *not* here: the organization's own monthly cap. That limit is not
    this agent's to describe - it stops every agent in the organization, its
    ceiling is set in the organization's settings, and an agent's author cannot
    raise it. Its alert goes to the organization's admins and is not
    configurable from a spec.
    """

    model_config = ConfigDict(extra="forbid")

    budget: AlertSpec = Field(
        default_factory=lambda: AlertSpec(to=_admins_and_owner()),
        description="This agent's own monthly cap stopped a run",
    )
    approvals: AlertSpec = Field(
        default_factory=lambda: AlertSpec(to=_initiator_and_admins()),
        description="A tool call parked, and the run is waiting on a person",
    )
    usage: AlertSpec = Field(
        default_factory=lambda: AlertSpec(enabled=False, to=_admins_and_owner()),
        description="A periodic report of what this agent alone has spent",
    )

    @model_validator(mode="after")
    def _usage_has_no_initiator(self) -> NotificationSpec:
        """A weekly report is nobody's run.

        `INITIATOR` resolves to whoever started the run being reported on, and a
        scheduled summary of five thousand of them has no such person. Accepting
        it would mean an audience that silently contributes nothing.
        """
        if AlertAudience.INITIATOR in self.usage.to:
            raise ValueError(
                "A usage report has no initiator - it covers a period, not a run. "
                "Use `admins`, `owner` or `chosen`."
            )
        return self


class ObservabilitySpec(BaseModel):
    """Where this agent's traces go.

    Per agent rather than per deployment because the interesting case is a
    client's agent whose traces belong in the client's own Logfire project, not
    in the operator's. The deployment-wide configuration stays as it is and
    keeps receiving everything else; this only redirects the runs of the agent
    that asks for it.

    The token is a reference, never a value - like every other credential a spec
    names. A spec is exported as YAML into somebody's repository, and a write
    token in a checked-in file is a token that has to be rotated.

    `organization` and `project` are the other half of that redirection, and they
    are here rather than in deployment settings for the same reason the token is:
    a token is a *write* credential and names neither, so a deployment knows
    where it sends an agent's traces and not where to read them. Both are slugs a
    client tells us; nothing can derive them. With neither set the run's trace id
    is still recorded and no link is offered - which is a configuration fact
    rather than a promise the schema is failing to keep (#206).
    """

    model_config = ConfigDict(extra="forbid")

    token_secret_id: UUID | None = Field(
        default=None,
        description="The organization secret holding a Logfire write token",
    )
    # A slug, not a length. Both are interpolated into a Logfire URL path when a
    # run's trace link is built, so a value with a slash, a dot-segment or a
    # query character would escape the path rather than name a project - a
    # length bound alone does not stop that. The pattern is the shape Logfire
    # slugs actually take: lowercase alphanumerics in hyphen-joined segments.
    organization: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="The Logfire organization slug these traces land in, for a link into them",
    )
    project: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="The Logfire project slug, alongside `organization`",
    )
    service_name: str | None = Field(
        default=None,
        max_length=128,
        description="What this agent is called in Logfire; defaults to the agent's name",
    )
    environment: str | None = Field(
        default=None,
        max_length=64,
        description="Logfire environment - production, staging, a client's name",
    )


class ModelSettingsSpec(BaseModel):
    """How this agent asks its model to behave.

    A deliberately small window onto Pydantic AI's `ModelSettings`. The full
    set includes escape hatches for someone debugging a provider - raw bodies,
    raw headers, token biases - which in a Builder are an invitation to paste
    something that breaks a published agent, and knobs that only some providers
    implement, which quietly mean something else after a model swap.
    `_MODEL_SETTINGS_WITHDRAWN` says why each excluded key went. What is left
    is what an agent author reaches for: how varied the answer is, how long it
    may be, how long it may take, and whether tools may run at once.

    Reasoning is not here. It is the `thinking` capability, and a second
    control writing the same provider parameter would disagree with it silently.

    **Every field is optional and unset means unset**, which is the one property
    the rest of this model is arranged around. `None` is not "send the
    provider's default" - it is "do not send this parameter", and the difference
    is a run that fails: reasoning models reject `temperature` outright, so an
    agent that never chose one must produce a request with no `temperature` key
    at all. Hence the serializer: an unset field is *absent* from the stored
    spec rather than stored as `null`, so nothing downstream - the merge in
    `app/agents/factory.py`, a YAML export, the Builder deciding whether to
    show a field as touched - has to know that a `null` here means "no".
    """

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description=(
            "How varied the answer is: near 0 for analysis and classification, "
            "higher for drafting. Some providers cap this at 1, and reasoning "
            "models reject it entirely - leave it unset there."
        ),
    )
    top_p: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description=(
            "Nucleus sampling: consider only the most likely tokens making up "
            "this much probability mass. Set this or temperature, not both."
        ),
    )
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=200_000,
        description="The longest answer the model may generate, in tokens",
    )
    parallel_tool_calls: bool | None = Field(
        default=None,
        description=(
            "Whether the model may call several tools in one step. Turning it "
            "off makes a run's tool calls arrive one at a time, which is easier "
            "to follow and to approve."
        ),
    )
    timeout: float | None = Field(
        default=None,
        gt=0.0,
        le=600.0,
        description=(
            "How long one model request may take, in seconds, before it is "
            "abandoned. An agent answering someone in a chat window has a "
            "deadline the provider's own default does not know about."
        ),
    )

    @model_serializer
    def _only_what_was_set(self) -> dict[str, float | int | bool]:
        """Serialise the settings this agent actually chose, and no others.

        The same fix `ToolOverride` needed, for a sharper reason: a `null`
        that survives to :func:`app.agents.factory.build_agent` is merged over
        the model profile's own value and then handed to the provider, so one
        unset field would both discard the profile's temperature and send
        `temperature: null` to a model that refuses the parameter.
        """
        return {
            name: value
            for name in type(self).model_fields
            if (value := getattr(self, name)) is not None
        }


DelegationMode = Literal["sync", "async", "auto"]


class McpServerRef(BaseModel):
    """One MCP connection this agent may call, and on whose account.

    An id would have been enough while a binding was only a reference. It is not
    one any more: `use_personal_when_available` is policy about *whose* account
    answers, and policy belongs on the binding rather than in a second list of
    ids kept in step with the first by hand.

    The organization's connection is always what is bound, and it is what the
    agent is reviewed against. The flag adds one narrow substitution on top of
    it: in a conversation that holds exactly one identified person and nobody
    else, that person's own connection to the same service is used instead. It
    is off by default because the default has to be the reviewable answer - an
    agent whose reach depends on who ran it is the thing
    :func:`build_toolsets_for_agent` exists to prevent, and this is the one
    place it is allowed, deliberately and per binding.

    Two constraints hold the substitution together, both checked at publish:

    - The bound connection must carry a `catalog_key`. That key is what says a
      person's Notion and the organization's Notion are the same service; a
      connection somebody pointed at a bare URL has nothing to match on.
    - Two flagged bindings may not share one `catalog_key`, because the
      substitution would then have two answers and no way to choose.
    """

    model_config = ConfigDict(extra="forbid")

    connection_id: UUID = Field(
        description="The organization's MCP connection. A personal one is refused at publish."
    )
    use_personal_when_available: bool = Field(
        default=False,
        description=(
            "Let a run reach this service through the runner's own connection "
            "when the conversation is theirs alone. Off by default; ignored "
            "wherever a second person can read the answer."
        ),
    )


class SubagentRef(BaseModel):
    """One published agent this agent may delegate to, pinned to a version.

    Two ids rather than one, and the second is the whole point. A delegate is a
    real agent - versioned, permission-checked at publish, with its own
    capabilities, its own model and its own collections - and a reference that
    named only the agent would let its behaviour change under a published parent
    with nothing recording that anything had changed. Pinning means a fix to a
    delegate reaches its callers when somebody says so, which is the same
    guarantee publishing gives everywhere else in this product.

    The cost of pinning is real and is paid in the Builder: a parent whose
    delegate has moved on is stale, and staleness that nothing surfaces is a bug
    frozen in place forever. The draft compares each pin against the delegate's
    current version and offers to move it.

    A pin whose version no longer exists **fails the run**, loudly, naming the
    delegate. Never a quiet fall back to the current version: the reason to pin
    is that nothing changes without a decision, and a silent upgrade is worse
    than a refusal because nobody finds out.
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: UUID = Field(description="The delegate. Must be an agent the publisher may run.")
    agent_version_id: UUID = Field(
        description="Which published version of it, pinned at publish time",
    )
    preferred_mode: DelegationMode | None = Field(
        default=None,
        description=(
            "Override the capability's mode for this delegate alone. A slow "
            "specialist is the case: the parent can carry on while it works."
        ),
    )


class SpecialistSpec(BaseModel):
    """A specialist defined inside another agent, rather than published.

    Worth having, and worth being honest about. A "summarise this in three
    bullets" specialist should not require somebody to publish an agent, and this
    is that: a name, a description the parent's model reads before delegating,
    instructions, and - because a summariser that cannot read the collection is
    useless - its own capabilities, collections and skills.

    Which makes it an agent in every way except one, and the exception is the
    important one: **a specialist is not versioned.** It has no version row, it
    cannot be pinned, nothing else can reference it, and editing the parent
    changes it. That is the difference between this and :class:`SubagentRef`, and
    it is why the Builder must present them as two different things rather than
    two tabs of one.

    The risk this shape exists to contain is a second, parallel notion of
    "agent" - one that publish validation does not walk and the permission model
    cannot see. It is contained by refusing to write a second format: this is a
    *typed subset of* :class:`AgentSpec`, using the same
    :class:`CapabilityBindingSpec`, validated by the same recursive pass in
    `validate_spec`, and assembled by the same `build_agent`. One spec type, one
    validator, one builder, one Builder component, each used recursively. If any
    of those five grows a second copy for specialists, the copy is the bug.

    Deliberately absent, each because it only means something for a thing with a
    version or an owner:

    - `budget` - inside a delegation the *parent's* caps bind. Two budget guards
      metering one shared ledger would double-count every request.
    - `notifications` and `observability` - a specialist is not the subject of an
      alert or a Logfire service; the run it happens inside is.
    - `mcp_servers` - an MCP connection is organization-scoped configuration,
      and reaching one through a specialist nobody published is the wrong door.
      There is deliberately **no** route to one from here: `share_with_delegates`
      lends *capability bindings*, and an MCP connection is not a capability, so
      naming one there would configure nothing. A specialist that needs an
      external tool is a specialist that should be a published agent.
    - `subagents` - a specialist does not delegate further. Nesting is what
      `max_depth` bounds, and it is bounded for published delegates, which are
      reviewable.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description=(
            "How the parent's model addresses this specialist. Constrained to what "
            "a tool argument can carry, because that is what it becomes."
        ),
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
        description=(
            "What the parent's model reads when deciding whether to delegate here. "
            "The highest-leverage prompt in a delegation - 'researches a topic and "
            "cites sources' gets used; 'helper' does not."
        ),
    )
    instructions: str = Field(
        min_length=1,
        description="The specialist's system prompt. Its behaviour lives here, not in code.",
    )
    model_profile_id: UUID | None = Field(
        default=None,
        description="Which model profile it runs on; null runs it on the parent's",
    )
    model_settings: ModelSettingsSpec = Field(
        default_factory=ModelSettingsSpec,
        description="Per-specialist overrides on top of its profile",
    )
    capabilities: list[CapabilityBindingSpec] = Field(
        default_factory=list,
        description=(
            "What this specialist can do. Validated exactly as the parent's are, "
            "including scopes and secrets, so a specialist cannot be the quiet "
            "route to a capability the organization has not granted."
        ),
    )
    collection_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Knowledge collections it may search. Checked at publish against the "
            "publisher's own access - a specialist is a tempting place to smuggle "
            "in a collection nobody may read, precisely because it does not look "
            "like an agent."
        ),
    )
    skill_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Skills it may read. Checked at publish against the publisher's own "
            "access, exactly as `collection_ids` is - a skill is know-how somebody "
            "wrote, and a private one bound here would be read by every run."
        ),
    )
    context_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Context files it injects or links. Checked at publish against the "
            "publisher's own access, exactly as `skill_ids` is - a file's body "
            "reaches every run, so a specialist can only lend what its publisher "
            "could read."
        ),
    )
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            "How many model requests this specialist may make per delegation. "
            "Null uses the platform default. This is the only thing between a "
            "delegation and a loop that delegates to a loop."
        ),
    )
    preferred_mode: DelegationMode | None = Field(
        default=None,
        description="Override the capability's mode for this specialist alone",
    )

    @field_validator("capabilities")
    @classmethod
    def _ids_are_unique(
        cls, capabilities: list[CapabilityBindingSpec]
    ) -> list[CapabilityBindingSpec]:
        """A capability bound twice would silently shadow itself.

        The same rule as :class:`AgentSpec`, restated rather than shared, because
        a `field_validator` is not inherited across unrelated models - and a
        specialist that could bind `knowledge` twice would build one of the two
        and give no indication which.
        """
        counts = Counter(capability.id for capability in capabilities)
        duplicates = sorted(cap_id for cap_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"Capability bound more than once: {', '.join(duplicates)}")
        return capabilities

    def bindings(self) -> list[CapabilityBinding]:
        """The specialist's capabilities as the registry consumes them."""
        return [capability.to_binding() for capability in self.capabilities]

    def to_agent_spec(self, *, fallback_model_profile_id: UUID | None) -> AgentSpec:
        """This specialist as the spec the factory already knows how to build.

        The one method that keeps "one spec type, one validator, one builder" true
        rather than aspirational. A specialist is a subset of an agent, so the way
        to build one is to say which agent it is and hand it to `build_agent` -
        not to write a second assembly path that will drift from the first the
        moment a field is added to either.

        `fallback_model_profile_id` is the parent's, used when the specialist
        names none: a specialist with no model of its own runs on the model of the
        agent that called it, which is both the least surprising answer and the
        only one that works when the parent is the only agent whose profile the
        author chose.

        The fields this drops are the ones :class:`SpecialistSpec` deliberately
        does not have - budget, notifications, observability, MCP connections,
        subagents - so they arrive at their `AgentSpec` defaults: no cap of its
        own (the run's caps bind), no alerts of its own, no Logfire project of its
        own, no connections, and no delegating further.
        """
        return AgentSpec(
            name=self.name,
            description=self.description,
            instructions=self.instructions,
            model_profile_id=self.model_profile_id or fallback_model_profile_id,
            model_settings=self.model_settings,
            capabilities=self.capabilities,
            collection_ids=self.collection_ids,
            skill_ids=self.skill_ids,
            context_ids=self.context_ids,
            max_steps=self.max_steps,
        )


def _binding_id(binding: Any) -> Any:
    """The capability id of a binding, raw from JSON or already parsed."""
    return binding.get("id") if isinstance(binding, dict) else getattr(binding, "id", None)


def _with_thinking_binding(data: Any, effort: Any) -> Any:
    """Express a version-5 `thinking` setting as a binding on the capability.

    `False` and a missing key both mean "do not think", and the way to say
    that now is not to bind the capability - which is also what the picker
    means by leaving it off. Anything else is a level, and `True` is the
    provider's own default effort, which is what an unset `effort` asks for.
    """
    if not effort:
        return data
    capabilities = list(data.get("capabilities") or [])
    if any(_binding_id(binding) == _THINKING_CAPABILITY for binding in capabilities):
        return data
    capabilities.append(
        {
            "id": _THINKING_CAPABILITY,
            "config": {} if effort is True else {"effort": effort},
        }
    )
    return {**data, "capabilities": capabilities}


class AgentSpec(BaseModel):
    """Everything that defines an agent's behaviour.

    Deliberately excluded: anything about *where* the agent runs (surfaces,
    channels) and anything about *who* may use it (owner, sharing). Those are
    deployment and access facts; keeping them out means the same spec can be
    exported, reviewed and reused across organizations.
    """

    model_config = ConfigDict(extra="forbid")

    spec_version: int = Field(default=SPEC_VERSION)

    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    instructions: str = Field(
        default="",
        description="The system prompt. The agent's behaviour lives here, not in code.",
    )

    model_profile_id: UUID | None = Field(
        default=None,
        description="Which of the organization's model profiles to run on; null uses the default",
    )
    model_settings: ModelSettingsSpec = Field(
        default_factory=ModelSettingsSpec,
        description="Per-agent overrides on top of the profile (temperature, max_tokens...)",
    )

    capabilities: list[CapabilityBindingSpec] = Field(default_factory=list)
    collection_ids: list[UUID] = Field(
        default_factory=list,
        description="Knowledge collections this agent may search",
    )
    skill_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Skills this agent may read. Checked at publish against the "
            "publisher's own access: binding a skill hands its body and its files "
            "to every run of the agent, so it can only lend what the publisher "
            "could read themselves."
        ),
    )
    context_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Context files this agent injects into its instructions or exposes "
            "through the `context` capability's read tool. Checked at publish "
            "against the publisher's own access, exactly as `skill_ids` is: a "
            "file's body reaches every run, so the agent can only lend what the "
            "publisher could read themselves."
        ),
    )
    mcp_servers: list[McpServerRef] = Field(
        default_factory=list,
        description=(
            "Organization-scoped MCP connections this agent may call, each with "
            "the one policy a binding carries. Personal connections are refused "
            "at publish: a published agent's reach cannot depend on whose "
            "session runs it, except where a binding says so explicitly."
        ),
    )

    subagents: list[SubagentRef] = Field(
        default_factory=list,
        description=(
            "Published agents this agent may delegate to, each pinned to a "
            "version. Top level rather than inside the delegation capability's "
            "config, for the same reason `collection_ids` and `mcp_servers` "
            "are: a reference to another row in this organization is a property "
            "of the agent, it is what publish validation walks, and it is what "
            "makes the `agents:run` check on each one a sibling of the collection "
            "check rather than something invented inside one capability. The "
            "capability's own config then carries policy only - depth, fan-out, "
            "mode, and the inline specialists, which are not references at all."
        ),
    )

    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description=(
            "How many model requests one run may make before it is stopped. "
            "Null uses the platform default; a tool loop is what this catches."
        ),
    )

    budget: BudgetSpec | None = None

    notifications: NotificationSpec = Field(
        default_factory=NotificationSpec,
        description=(
            "Which of this agent's alerts are sent and who hears each one. "
            "Defaulted, so an agent published before this existed keeps the "
            "behaviour it had: budget breaches to the admins and the owner, "
            "approvals to whoever asked plus the admins, no usage report."
        ),
    )

    observability: ObservabilitySpec | None = Field(
        default=None,
        description="Send this agent's traces to a Logfire project of its own",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_version_9_mcp_server_ids(cls, data: Any) -> Any:
        """Let a spec written against `mcp_server_ids` load as `mcp_servers`.

        Version 10 turned a list of ids into a list of references so the binding
        could carry `use_personal_when_available`. Without this, `extra="forbid"`
        would refuse every stored spec that names an MCP server - a 500 on every
        run of something nobody touched - and the ids are the same ids, so there
        is nothing to decide: each becomes a reference with the flag off, which
        is the behaviour those specs already have.

        An explicit `mcp_servers` wins, so re-reading a migrated spec changes
        nothing.
        """
        if not isinstance(data, dict) or "mcp_server_ids" not in data:
            return data
        legacy = data["mcp_server_ids"]
        migrated = {key: value for key, value in data.items() if key != "mcp_server_ids"}
        if "mcp_servers" in data or not isinstance(legacy, list):
            return migrated
        migrated["mcp_servers"] = [{"connection_id": value} for value in legacy]
        return migrated

    @model_validator(mode="before")
    @classmethod
    def _migrate_version_5_model_settings(cls, data: Any) -> Any:
        """Let a spec written against the old settings blob load unchanged.

        `model_settings` was `dict[str, Any]`, so a hand-written or imported
        spec may name any portable `ModelSettings` key. Refusing those now
        would mean a published agent that no longer parses - a 500 on every run
        of something nobody touched - so the keys this version withdrew are
        dropped here instead, loudly enough to find in a log.

        `thinking` is the exception: it is folded into a binding on the
        capability that now owns it, because dropping it would quietly stop an
        agent reasoning. An explicit binding wins, so a spec this already
        migrated is unchanged by a second read.
        """
        if not isinstance(data, dict):
            return data
        settings = data.get("model_settings")
        if not isinstance(settings, dict):
            return data
        withdrawn = _MODEL_SETTINGS_WITHDRAWN & settings.keys()
        if not withdrawn:
            return data

        logger.warning(
            "Dropping model settings this spec version no longer exposes: %s",
            ", ".join(sorted(withdrawn)),
        )
        migrated = {
            **data,
            "model_settings": {
                key: value for key, value in settings.items() if key not in withdrawn
            },
        }
        return _with_thinking_binding(migrated, settings.get(_THINKING_SETTING))

    @field_validator("capabilities")
    @classmethod
    def _ids_are_unique(
        cls, capabilities: list[CapabilityBindingSpec]
    ) -> list[CapabilityBindingSpec]:
        """A capability bound twice would silently shadow itself."""
        counts = Counter(capability.id for capability in capabilities)
        duplicates = sorted(cap_id for cap_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"Capability bound more than once: {', '.join(duplicates)}")
        return capabilities

    @field_validator("subagents")
    @classmethod
    def _one_pin_per_delegate(cls, subagents: list[SubagentRef]) -> list[SubagentRef]:
        """The same agent cannot be delegated to twice.

        Two pins of one agent are two delegates with one name - the delegate's
        own, which is what the parent's model addresses it by - so the model
        would have no way to say which it meant and the second would shadow the
        first. Refused here rather than at publish because it needs nothing from
        the database, so a hand-written YAML import is caught by the same rule as
        the Builder.
        """
        counts = Counter(ref.agent_id for ref in subagents)
        duplicates = sorted(str(agent_id) for agent_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"Agent delegated to more than once: {', '.join(duplicates)}")
        return subagents

    def bindings(self) -> list[CapabilityBinding]:
        """The spec's capabilities as the registry consumes them."""
        return [capability.to_binding() for capability in self.capabilities]

    def to_yaml(self) -> str:
        """Render the spec for a client's git repository.

        Keys keep spec order rather than being sorted, so a diff reflects what
        changed rather than where it happens to sort. UUIDs become strings so
        the file round-trips through any YAML reader.
        """
        payload = self.model_dump(mode="json", exclude_none=True)
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)

    @classmethod
    def from_yaml(cls, text: str) -> AgentSpec:
        """Parse a spec written or edited by hand.

        Raises:
            ValueError: If the document is not a mapping. Pydantic reports field
                problems itself, but a list or a bare string reaches it as an
                unhelpful type error.
        """
        loaded = yaml.safe_load(text)
        if not isinstance(loaded, dict):
            raise ValueError("An agent spec must be a YAML mapping")  # noqa: TRY004
        return cls.model_validate(loaded)
