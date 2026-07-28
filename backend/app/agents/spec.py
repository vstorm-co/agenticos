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

# Bumped only when the shape changes incompatibly. Stored with every version so
# an old row can be read by the loader that understands it.
#
# 3 added `tool_approval`. A version-2 spec has no such key and gets an empty
# one, which resolves to exactly the behaviour it had: whatever `approval` (or
# the capability's `side_effecting` flag) said, for every tool at once.
#
# 4 added `tool_overrides` and took the knowledge capability's own `tool_name` /
# `tool_description` config keys away. A version-3 spec that used them is folded
# into the general field on load, so what its model sees does not change.
#
# 5 added `secret_id` on a capability binding. A version-4 spec has no such key
# and gets `None`, which is exactly right: no capability it could have bound
# declared a secret requirement, so there was nothing to reference.
#
# 6 turned `model_settings` from an unvalidated blob into `ModelSettingsSpec`,
# which names the settings an agent author may set and refuses everything else.
# A version-5 spec keeps the keys that survived; `thinking` becomes a binding on
# the capability that now owns it, and the rest are dropped on load - see
# `_MODEL_SETTINGS_WITHDRAWN` for why each one went.
SPEC_VERSION = 6

ApprovalMode = Literal["default", "required", "never"]

# The one capability that invented per-agent renaming for itself, and the tool
# it renamed. Ids are permanent, which is what makes naming them in a migration
# safe.
_LEGACY_RENAME_CAPABILITY = "knowledge"
_LEGACY_RENAME_TOOL = "search_documents"

# The capability that now owns reasoning, and the model setting it replaced.
_THINKING_CAPABILITY = "thinking"
_THINKING_SETTING = "thinking"

# Portable `ModelSettings` keys a version-5 spec could carry that this version
# deliberately does not expose. Named one by one rather than dropped as "whatever
# we no longer recognise", because `extra="forbid"` on the settings model is what
# catches a typo, and a blanket rule would swallow the typo with them.
_MODEL_SETTINGS_WITHDRAWN = frozenset(
    {
        # Escape hatches for someone debugging a provider, not agent
        # configuration. Pasted into a Builder they break a published agent in a
        # way no validation here could see coming.
        "extra_body",
        "extra_headers",
        "logit_bias",
        # Repetition dials and top-k sampling: real knobs, but each is missing
        # from a provider an organization is likely to be on, so an agent
        # carrying one silently means something different after a model swap.
        "frequency_penalty",
        "presence_penalty",
        "top_k",
        # Best-effort at every provider that accepts it at all. A published
        # agent pinned to a seed is not more reproducible, only harder to reason
        # about; determinism belongs to an eval harness.
        "seed",
        # Truncates the answer mid-sentence when it fires unexpectedly, which
        # reads as a broken agent rather than a configured one - and in a tool
        # loop it can cut a call in half.
        "stop_sequences",
        # A commercial decision about the credential, not about the agent. It
        # belongs to the model profile, where the organization's relationship
        # with the provider already lives.
        "service_tier",
        # Setting `'required'` or a tool list statically raises `UserError`
        # before the first request, and `'none'` contradicts the capability
        # picker one tab away.
        "tool_choice",
        # Owned by the `thinking` capability. Folded into a binding rather than
        # dropped, so an agent that reasoned before an upgrade still reasons.
        _THINKING_SETTING,
    }
)


class CapabilityBindingSpec(BaseModel):
    """One capability as this agent uses it.

    A capability is the unit worth switching on or off, and it covers things
    that are not tools at all, like a guardrail or a compaction strategy.

    Two things are decided finer than that, and both key on a tool's stable id.
    A capability that reads and writes is two decisions wearing one name, so
    ``tool_approval`` overrides ``approval`` for one tool - approve the write,
    leave the read alone. And what the model *reads* about a tool is the
    strongest prompt in the product, so ``tool_overrides`` reworks its name and
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

        ``knowledge`` used to carry ``tool_name`` and ``tool_description`` in
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
    """Spending limits for this agent.

    Both limits exist because they fail differently: a per-run cap stops one
    runaway conversation, a monthly cap stops a slow leak nobody is watching.
    """

    model_config = ConfigDict(extra="forbid")

    max_per_run_usd: float | None = Field(default=None, gt=0)
    monthly_usd: float | None = Field(default=None, gt=0)


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
    """

    model_config = ConfigDict(extra="forbid")

    token_secret_id: UUID | None = Field(
        default=None,
        description="The organization secret holding a Logfire write token",
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

    A deliberately small window onto Pydantic AI's ``ModelSettings``. The full
    set includes escape hatches for someone debugging a provider - raw bodies,
    raw headers, token biases - which in a Builder are an invitation to paste
    something that breaks a published agent, and knobs that only some providers
    implement, which quietly mean something else after a model swap.
    ``_MODEL_SETTINGS_WITHDRAWN`` says why each excluded key went. What is left
    is what an agent author reaches for: how varied the answer is, how long it
    may be, how long it may take, and whether tools may run at once.

    Reasoning is not here. It is the ``thinking`` capability, and a second
    control writing the same provider parameter would disagree with it silently.

    **Every field is optional and unset means unset**, which is the one property
    the rest of this model is arranged around. ``None`` is not "send the
    provider's default" - it is "do not send this parameter", and the difference
    is a run that fails: reasoning models reject ``temperature`` outright, so an
    agent that never chose one must produce a request with no ``temperature`` key
    at all. Hence the serializer: an unset field is *absent* from the stored
    spec rather than stored as ``null``, so nothing downstream - the merge in
    ``app/agents/factory.py``, a YAML export, the Builder deciding whether to
    show a field as touched - has to know that a ``null`` here means "no".
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
        # High enough for the longest output any current model will produce, low
        # enough that a mistyped one is refused here rather than by the provider.
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

        The same fix ``ToolOverride`` needed, for a sharper reason: a ``null``
        that survives to :func:`app.agents.factory.build_agent` is merged over
        the model profile's own value and then handed to the provider, so one
        unset field would both discard the profile's temperature and send
        ``temperature: null`` to a model that refuses the parameter.
        """
        return {
            name: value
            for name in type(self).model_fields
            if (value := getattr(self, name)) is not None
        }


def _binding_id(binding: Any) -> Any:
    """The capability id of a binding, raw from JSON or already parsed."""
    return binding.get("id") if isinstance(binding, dict) else getattr(binding, "id", None)


def _with_thinking_binding(data: Any, effort: Any) -> Any:
    """Express a version-5 ``thinking`` setting as a binding on the capability.

    ``False`` and a missing key both mean "do not think", and the way to say
    that now is not to bind the capability - which is also what the picker
    means by leaving it off. Anything else is a level, and ``True`` is the
    provider's own default effort, which is what an unset ``effort`` asks for.
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
    skill_ids: list[UUID] = Field(default_factory=list)
    mcp_server_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Organization-scoped MCP connections this agent may call. Personal "
            "connections are refused at publish: a published agent's reach cannot "
            "depend on whose session runs it."
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

    observability: ObservabilitySpec | None = Field(
        default=None,
        description="Send this agent's traces to a Logfire project of its own",
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_version_5_model_settings(cls, data: Any) -> Any:
        """Let a spec written against the old settings blob load unchanged.

        ``model_settings`` was ``dict[str, Any]``, so a hand-written or imported
        spec may name any portable ``ModelSettings`` key. Refusing those now
        would mean a published agent that no longer parses - a 500 on every run
        of something nobody touched - so the keys this version withdrew are
        dropped here instead, loudly enough to find in a log.

        ``thinking`` is the exception: it is folded into a binding on the
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
            # ValueError, not TypeError: this is a validation failure on
            # user-supplied YAML, and ValueError is what Pydantic validators
            # raise and what every caller of this function catches.
            raise ValueError("An agent spec must be a YAML mapping")  # noqa: TRY004
        return cls.model_validate(loaded)
