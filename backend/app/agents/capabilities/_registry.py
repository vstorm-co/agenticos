"""Capability registry - the boundary between code and configuration.

The platform's central tension: we write capabilities in typed, tested Python
while clients compose agents without writing any. Resolving it by making
behaviour editable in a browser would put a code editor in the product;
resolving it by hardcoding per client would fork the codebase per deployment.

So: **code defines capabilities, configuration composes them.** A developer
declares a capability once with metadata describing how it may be configured.
An agent spec references it by a stable id plus a validated config blob.
Configuration can only reach what code registered.

Why capabilities rather than individual tools: a capability is the unit that
actually makes sense to switch *on or off*. "Knowledge search" is one decision,
not one decision per tool it happens to expose. Capabilities also cover things
that are not tools at all - a budget guard, a compaction strategy, a guardrail -
so one concept covers everything an agent is assembled from instead of two that
overlap awkwardly.

Approval is the exception, and the reason a capability declares its `tools`:
"may this agent write files" and "may it read them" are two decisions even
though one capability answers both. Enabling stays per capability; approving
happens per tool.

Presentation is the second exception. A tool's description is the highest-leverage
prompt in the product - it is what the model reads before deciding to call it -
and its name measurably changes behaviour, so a binding may override both per
tool. That override is keyed on the tool's stable id and applied here, once, for
every capability. It used to be a field one capability invented inside its own
config; two ways to rename one tool disagree eventually, and the disagreement is
silent.

Three consequences worth stating:

*Ids are permanent.* A spec in a client's git repository names `knowledge`.
Renaming the Python class is free; changing the id breaks every stored spec.

*Metadata serves two readers.* The description is what a person reads in the
Builder; `config_schema` is both validation and the source of the form.

*Validation happens at publish, not at run time.* An unknown id or an ungranted
scope is rejected while someone is looking at a form, not mid-conversation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)
from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities._overrides import ToolOverrides
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import SecretRequirement, StorableSecret

logger = logging.getLogger(__name__)

# What every model provider accepts as a callable tool name. A rename is what
# the model has to emit, so `send email` is not a name - it is a tool that can
# never be called.
TOOL_NAME_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,64}")


class ToolOverride(BaseModel):
    """How one binding presents one tool to its model.

    Both fields are prompt surface. The description is what the model reads
    before deciding whether to call the tool; the name is read alongside it and
    steers just as hard - `search_refund_policy` is not `search_documents`.
    An agent that needs different behaviour from the same tool usually needs
    these reworded, not a second tool written.

    Neither field can reach the tool's identity: `id` stays what code declared
    it, which is what keeps an approval decision attached to a renamed tool.

    A field nobody set is *absent* from the serialised spec rather than stored
    as `null`. "Explicitly no name" is not a state this can be in, and a
    stored `null` reads as one: the Builder marks a field as overridden when
    the binding has a value for it, and a `null` arriving back from a save
    made a reverted field look permanently overridden.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(
        default=None,
        max_length=64,
        description="What the model calls this tool, e.g. 'search_refund_policy'",
    )
    description: str | None = Field(
        default=None,
        max_length=1024,
        description="What the model reads before deciding to call it",
    )

    @model_serializer
    def _only_what_was_set(self) -> dict[str, str]:
        return {
            field: value
            for field, value in (("name", self.name), ("description", self.description))
            if value is not None
        }


@dataclass(frozen=True)
class CapabilityBinding:
    """One capability as an agent uses it: which, configured how, named how.

    `config` is what the capability's own schema accepts. `tool_overrides`
    is the general mechanism for presentation, keyed by each tool's stable id,
    and applies to every capability rather than the ones whose author thought
    of it.

    `secret_id` names which of the organization's secrets satisfies the
    capability's requirement - an id, never a value. A spec is exported to a
    client's git repository, so the only thing it may carry is a reference.
    """

    capability_id: str
    config: dict[str, Any] = field(default_factory=dict)
    tool_overrides: Mapping[str, ToolOverride] = field(default_factory=dict)
    secret_id: UUID | None = None
    enabled: bool = True


CapabilityBuilder = Callable[["CapabilityBuildContext"], AbstractCapability[Any] | None]


@dataclass(frozen=True)
class CapabilityBuildContext:
    """What a builder receives when an agent is assembled.

    `config` is already validated against the capability's schema, so a
    builder reads its fields without re-checking. `resources` carries things
    resolved from the database for this run - collection names, skills - which
    a capability may need but must never fetch itself.

    `secret` is the unsealed credential the capability declared it needs, and
    is present exactly when it declared one. It is a field of its own rather
    than an entry in `resources` because the two have different rules: a
    resource may be logged, and a secret may not. Every secret-bearing field is
    a `SecretStr`, so this dataclass masks itself in a repr - which is the way
    a plaintext key usually escapes.
    """

    binding: CapabilityBinding
    config: BaseModel | None
    resources: dict[str, Any] = field(default_factory=dict)
    secret: StorableSecret | None = None


class CapabilityToolInfo(BaseModel):
    """One tool a capability contributes, as the Builder lists it.

    A Pydantic model rather than a dataclass because it is served straight out
    of the capability catalog: the Builder needs the tool names to offer
    per-tool approval, and it cannot offer what the registry never described.

    `name` and `description` are the deployment's defaults, exactly as code
    declared them - the catalog answers "what tools exist and what do they say",
    which is a question about the deployment and not about one agent. A binding's
    overrides are resolved where the binding is in hand, by
    :meth:`CapabilityDef.effective_tools`, which returns this same shape with them
    applied.

    `description` is the tool's own docstring summary - the same sentence the
    model reads before deciding to call it. The person choosing what needs
    approval and the model choosing when to act should be looking at the same
    text, not at two paraphrases that drift apart.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    """Stable identity, defined in code and never configurable.

    Separate from `name` because a binding keys its approval decision on
    this. A tool the model sees under a different name must still be the tool
    an operator gated - otherwise renaming one silently removes its gate, and
    a side-effecting call goes unattended with nothing reporting it.
    """

    name: str = ""
    """What the model sees. Defaults to `id`; only a rename makes them differ."""

    description: str

    side_effecting: bool | None = None
    """Whether *this tool* acts on the world, when the capability is not one answer.

    `None` - the default - defers to `CapabilityDef.side_effecting`, so every
    capability that declares nothing behaves exactly as it did.

    It exists because a capability can genuinely be two things at once. One that
    reads a filesystem *and* writes to it *and* runs a shell has no single
    honest value: marking the capability side-effecting makes an agent ask
    permission to list a directory, and not marking it lets a write run
    unattended. The author would then hand-write a `tool_approval` override per
    tool in every spec, and the one they forget is the dangerous one.

    A binding still overrides this - `tool_approval` is the operator's decision
    and beats the code's.
    """

    @model_validator(mode="before")
    @classmethod
    def _name_defaults_to_id(cls, data: Any) -> Any:
        """A tool nobody renamed is seen under the name it was declared with.

        Runs *before* validation rather than after: this model is frozen, so an
        after-validator cannot assign and returning a copy is silently
        discarded - which left every tool with an empty name and an approval
        gate that matched nothing.
        """
        if isinstance(data, dict) and not data.get("name"):
            return {**data, "name": data.get("id", "")}
        return data


@dataclass(frozen=True)
class CapabilityDef:
    """A registered capability and everything needed to expose and build it."""

    id: str
    name: str
    category: str
    description: str
    builder: CapabilityBuilder
    tools: tuple[CapabilityToolInfo, ...]
    config_schema: type[BaseModel] | None = None
    side_effecting: bool = False
    scopes: frozenset[str] = frozenset()
    # The credential this capability needs, declared as a *kind* - never as an
    # instance. Code says "I need an API key"; configuration says which one.
    secret: SecretRequirement | None = None

    def needs_secret(self, config: BaseModel | None) -> bool:
        """Whether a binding with this configuration must name a secret.

        One answer, consulted by publish validation and by the build, so the
        two can never disagree - which would mean an agent that publishes and
        then refuses to run, or worse, the reverse.
        """
        if self.secret is None:
            return False
        condition = self.secret.required_when
        return condition is None or condition.is_met(config)

    @property
    def tool_ids(self) -> frozenset[str]:
        """The stable ids this capability's tools are declared under."""
        return frozenset(tool.id for tool in self.tools)

    def effective_tools(
        self, overrides: Mapping[str, ToolOverride]
    ) -> tuple[CapabilityToolInfo, ...]:
        """This capability's tools as one binding presents them to its model.

        The single answer to "what will the model see", so nothing has to derive
        it twice and get two answers. The approval gate matches on the name the
        model called, which is this one - reading `tools` there instead would
        gate a tool nobody can call and leave the renamed one running
        unattended.
        """
        return tuple(
            tool
            if (override := overrides.get(tool.id)) is None
            else CapabilityToolInfo(
                id=tool.id,
                name=override.name or tool.name,
                description=override.description or tool.description,
                # Carried, not defaulted. A rename that dropped it would put the
                # tool back on the capability's answer - so renaming `execute`
                # on a capability whose reads are free would silently ungate the
                # one call worth gating, which is the exact failure `id` exists
                # to prevent.
                side_effecting=tool.side_effecting,
            )
            for tool in self.tools
        )

    def validate_config(self, raw: dict[str, Any]) -> BaseModel | None:
        """Parse a spec's config blob against this capability's schema.

        Raises:
            BadRequestError: If it does not match, carrying the field errors the
                Builder form needs to point at the right input.
        """
        if self.config_schema is None:
            return None
        try:
            return self.config_schema.model_validate(raw or {})
        except ValidationError as exc:
            raise BadRequestError(
                message=f"Invalid configuration for capability '{self.id}'",
                details={"capability_id": self.id, "errors": exc.errors(include_url=False)},
            ) from exc

    def config_json_schema(self) -> dict[str, Any] | None:
        """The JSON Schema the Builder generates a form from."""
        if self.config_schema is None:
            return None
        return self.config_schema.model_json_schema()


REGISTRY: dict[str, CapabilityDef] = {}

# Whether the builtin capability modules have been imported. Not a cache of the
# registry itself - tests add and remove entries around it - only of the import.
_builtins_loaded = False


def register(
    *,
    id: str,
    name: str,
    category: str,
    description: str,
    tools: Iterable[CapabilityToolInfo],
    config_schema: type[BaseModel] | None = None,
    side_effecting: bool = False,
    scopes: Iterable[str] = (),
    secret: SecretRequirement | None = None,
) -> Callable[[CapabilityBuilder], CapabilityBuilder]:
    """Register a capability builder.

    The decorated function receives a :class:`CapabilityBuildContext` and returns
    the capability instance to attach to the agent, or `None` when its config
    means it contributes nothing to this particular agent.

    `secret` declares that this capability cannot work without a credential of
    a given kind, in the same way `scopes` declares what the organization must
    have allowed. Which secret satisfies it is a binding's decision, checked at
    publish and injected here at build time; the capability never learns where
    it came from and the model never sees it at all.

    `SecretRequirement.required_when` narrows that to the configurations which
    actually authenticate. Without it, a capability offering both a keyless
    provider and a paid one has to choose which of the two to break. It is data
    rather than a predicate because the Builder has to ask for a key at exactly
    the moments this server will demand one, and only a value can cross the wire.

    `tools` has no default on purpose. It is what the Builder offers per-tool
    approval for and what the approval gate matches on, so a capability that
    declares nothing is a capability whose tools cannot be gated - and the
    dangerous half of that failure is silent: an author adds a second,
    side-effecting tool, forgets to declare it, and it runs unattended forever.
    Requiring the argument makes forgetting a `TypeError`; keeping it honest
    afterwards is the job of the drift test in
    `tests/test_capability_registry.py`, which builds every registered
    capability and compares this list against the tools the model is actually
    offered. A capability with no tools says so with `tools=()`, and one that
    declares a tool it deliberately does not wire names it in that test's own
    exception table, where the reason can be a sentence.
    """

    def decorator(builder: CapabilityBuilder) -> CapabilityBuilder:
        definition = CapabilityDef(
            id=id,
            name=name,
            category=category,
            description=description,
            builder=builder,
            tools=tuple(tools),
            config_schema=config_schema,
            side_effecting=side_effecting,
            scopes=frozenset(scopes),
            secret=secret,
        )
        existing = REGISTRY.get(definition.id)
        if existing is not None and existing is not definition:
            # Almost always a copy-paste in a new module. Letting the second
            # registration win would make an agent's behaviour depend on import
            # order - a bug that only appears in production.
            raise RuntimeError(
                f"Capability id '{definition.id}' is already registered by {existing.name!r}. "
                "Ids are part of the spec format and must be unique."
            )
        REGISTRY[definition.id] = definition
        return builder

    return decorator


def get(capability_id: str) -> CapabilityDef:
    """Look up a capability.

    Raises:
        BadRequestError: If no such capability exists, naming what is available.
    """
    load_builtins()
    definition = REGISTRY.get(capability_id)
    if definition is None:
        raise BadRequestError(
            message=f"Unknown capability: {capability_id}",
            details={"capability_id": capability_id, "available": sorted(REGISTRY)},
        )
    return definition


def all_capabilities() -> list[CapabilityDef]:
    """Every registered capability, ordered for a stable Builder picker."""
    load_builtins()
    return sorted(REGISTRY.values(), key=lambda d: (d.category, d.name))


def build(
    bindings: Iterable[CapabilityBinding],
    *,
    granted_scopes: frozenset[str] | None = None,
    resources: dict[str, Any] | None = None,
    secrets: Mapping[UUID, StorableSecret] | None = None,
) -> list[AbstractCapability[Any]]:
    """Assemble an agent's capabilities from its bindings.

    Args:
        bindings: The spec's capability list, in order.
        granted_scopes: What the organization allows. `None` skips the check
            and is for internal runs and tests only.
        resources: Values resolved from the database for this run.
        secrets: The unsealed secrets this run's bindings reference, keyed by id
            and already checked to belong to the organization.

    Raises:
        BadRequestError: On an unknown capability, invalid config, a scope the
            organization has not granted, or a required secret that is no longer
            available.
    """
    built: list[AbstractCapability[Any]] = []
    for binding in bindings:
        if not binding.enabled:
            continue
        definition = get(binding.capability_id)

        if granted_scopes is not None:
            missing = definition.scopes - granted_scopes
            if missing:
                raise BadRequestError(
                    message=(
                        f"Capability '{definition.id}' requires scopes this organization "
                        "has not granted"
                    ),
                    details={
                        "capability_id": definition.id,
                        "missing_scopes": sorted(missing),
                    },
                )

        config = definition.validate_config(binding.config)
        capability = definition.builder(
            CapabilityBuildContext(
                binding=binding,
                config=config,
                resources=resources or {},
                secret=_secret_for(definition, binding, config, secrets or {}),
            )
        )
        if capability is not None:
            # Stamped with the registry id rather than left to Pydantic AI's
            # class-name default: every tool definition carries the id of the
            # capability that contributed it, and that is how the approval gate
            # tells a gated tool from an ungated one. Stamped *before* wrapping,
            # because the wrapper adopts the id of what it wraps.
            capability.id = definition.id
            built.append(_as_bound(capability, binding.tool_overrides))
    return built


def _secret_for(
    definition: CapabilityDef,
    binding: CapabilityBinding,
    config: BaseModel | None,
    secrets: Mapping[UUID, StorableSecret],
) -> StorableSecret | None:
    """The credential this binding brings, if its capability asked for one.

    Publish validation already refused a binding whose reference was missing or
    the wrong kind, so reaching the refusal here means the secret was deleted
    *after* the agent was published. Refused rather than degraded: a capability
    whose whole job is calling an authenticated API does not do half of it, and
    a run that quietly dropped the call would answer as if the API had said no.

    Raises:
        BadRequestError: If a declared secret is not available for this run.
    """
    # Read out rather than reached through `definition.secret` below: a
    # requirement is what `needs_secret` consulted, and re-deriving it there is
    # what leaves a type checker unable to see that it cannot be None.
    requirement = definition.secret
    if requirement is None or not definition.needs_secret(config):
        # Still handed over when one was chosen anyway: a configuration that
        # does not require a key may still be able to use one.
        return secrets.get(binding.secret_id) if binding.secret_id else None
    secret = secrets.get(binding.secret_id) if binding.secret_id is not None else None
    if secret is None:
        raise BadRequestError(
            message=(
                f"Capability '{definition.id}' needs a secret this organization no longer has"
            ),
            details={
                "capability_id": definition.id,
                "secret_id": str(binding.secret_id) if binding.secret_id else None,
                "required_kind": requirement.kind.value,
            },
        )
    return secret


def _as_bound(
    capability: AbstractCapability[Any], overrides: Mapping[str, ToolOverride]
) -> AbstractCapability[Any]:
    """The capability as this binding presents it.

    Wrapping only when something is actually overridden keeps the common agent
    exactly what it was - and keeps `BuiltAgent.capabilities` readable, since
    a surface introspecting it should not have to see through a wrapper that
    changes nothing.
    """
    names = {
        tool_id: override.name
        for tool_id, override in overrides.items()
        if override.name is not None
    }
    descriptions = {
        tool_id: override.description
        for tool_id, override in overrides.items()
        if override.description is not None
    }
    if not names and not descriptions:
        return capability
    return ToolOverrides(wrapped=capability, names=names, descriptions=descriptions)


def load_builtins() -> None:
    """Import capability modules so their decorators run.

    A module nobody imports does not exist as far as the Builder is concerned,
    which is the intended coupling. What was *not* intended is that the coupling
    also ran through the caller: this was called from the FastAPI lifespan only,
    so every other entry point - the CLI, a worker, a migration script - saw an
    empty registry and refused to publish any agent, reporting the capability as
    unknown. Every lookup now loads first, and the flag keeps that free after the
    first call.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return

    from app.agents.capabilities import (  # noqa: F401 - imported for side effects
        charts,
        clock,
        code_execution,
        knowledge,
        sandbox,
        skills,
        subagents,
        thinking,
        web_research,
    )

    _builtins_loaded = True
    logger.debug("Capability registry loaded with %d entries", len(REGISTRY))
