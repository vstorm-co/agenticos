"""Building an agent for a voice call (#54).

A call runs the agent the spec describes through `Agent.realtime`, which
differs from a text run in five ways the factory has to absorb, all measured in
the spike (`.dev-agent/54/spike-findings.md` §2-3):

- tools are fixed at connect, so deferred tools and deferred capabilities that
  contribute a toolset are rejected - MCP toolsets go in undeferred, `ToolSearch`
  is dropped, and skills become toolless deferred leaves;
- a session cannot pause for approval, so `HandleDeferredToolCalls` resolves
  approvals inline;
- only `instructions=` reaches the session, never `system_prompt=`;
- model-request hooks never run, so `thinking` is mapped onto the realtime
  settings instead;
- four capabilities cannot run at all and are stripped, from the spec before
  the run is assembled and again in the factory.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic_ai.capabilities import AbstractCapability, Capability, ToolSearch
from pydantic_ai.settings import ThinkingEffort
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults, RunContext, ToolDefinition

from app.agents.capabilities import get as capability_def
from app.agents.capabilities.skills import Skills
from app.agents.capabilities.thinking import ThinkingConfig
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec

DeferredHandler = Callable[
    [RunContext[AgentDeps], DeferredToolRequests], Awaitable[DeferredToolResults]
]

SPOKEN_STYLE = """You are speaking with a person on a live voice call. Everything you say is heard, not read.
- Use short sentences. Never read out markdown, lists, tables, headings, links or code; say what they mean instead.
- Say numbers, dates, times and amounts the way a person would say them aloud.
- Before you act on a name, an amount, an address or a date, read it back and wait for a yes.
- When a tool needs approval, say that you are asking for it and wait. Never say an action is done until its result arrives.
- If a decision is denied or times out, say so plainly.
- If something you would normally do cannot be done on a call, say so plainly and suggest continuing in text chat."""
"""Appended to every agent's instructions in a call (Q12). Hearing is not reading:
a bullet list read aloud is noise, and a misheard amount acted on unread back is
the spike's 'Acme heard as Ahmad'."""


@dataclass(frozen=True)
class VoiceOptions:
    """What a voice call changes about how an agent is built.

    `on_deferred` resolves a gated call inline - the session cannot pause.
    `anonymous` is a widget or hosted-page visitor, who cannot approve, so gated
    tools are left out of the session entirely (the issue's rule). `briefing` is
    what a text turn on that embed would prepend to the visitor's words - the
    operator's placement context and the page's supplied variables.
    """

    on_deferred: DeferredHandler
    anonymous: bool = False
    voice_note: str | None = None
    language: str | None = None
    briefing: str | None = None


def voice_instructions(instructions: str, options: VoiceOptions) -> str:
    """The complete instructions a call is given: the spec's, the spoken style, an embed's
    briefing, the agent's note."""
    parts = [instructions.strip(), SPOKEN_STYLE]
    if options.language:
        parts.append(
            f"Speak in the language with ISO-639-1 code '{options.language}' unless the person asks otherwise."
        )
    if options.briefing:
        parts.append(options.briefing.strip())
    if options.voice_note:
        parts.append(options.voice_note.strip())
    return "\n\n".join(part for part in parts if part)


class _ToollessSkill(Capability[AgentDeps]):
    """A skill leaf that contributes no toolset at all.

    `pydantic-ai-skills` gives each deferred leaf an empty `FunctionToolset`
    rather than `None`, and realtime rejects any deferred capability that
    contributes a toolset - even an empty one. The skill's instructions and the
    container's `read_skill_resource` are unchanged.
    """

    def get_toolset(self) -> None:
        return None


def _toolless(capability: AbstractCapability[AgentDeps]) -> AbstractCapability[AgentDeps]:
    if isinstance(capability, Capability) and capability.defer_loading:
        return _ToollessSkill(
            id=capability.id,
            description=capability.get_description(),
            instructions=capability.get_instructions(),
            defer_loading=True,
        )
    return capability


def voice_skills(skills: Skills[AgentDeps]) -> AbstractCapability[AgentDeps]:
    """The skills capability with every leaf made toolless, through the library's own rewrite."""
    adapted = skills.visit_and_replace(_toolless)
    # `_toolless` replaces a leaf and never removes one, so the tree cannot come back empty.
    assert adapted is not None
    return adapted


@dataclass
class WithoutApprovalTools(AbstractCapability[AgentDeps]):
    """Leaves gated tools out of an anonymous caller's session.

    A visitor on a widget or a hosted page can approve nothing, so the tool is
    never offered rather than offered and refused.
    """

    names: frozenset[str]

    async def prepare_tools(
        self, ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]
    ) -> list[ToolDefinition]:
        return [tool for tool in tool_defs if tool.name not in self.names]


def voice_configured(configured: list[AbstractCapability[Any]]) -> list[AbstractCapability[Any]]:
    """The spec's built capabilities as a call can carry them: no tool search, toolless skills."""
    carried: list[AbstractCapability[Any]] = []
    for capability in configured:
        if isinstance(capability, ToolSearch):
            continue
        carried.append(voice_skills(capability) if isinstance(capability, Skills) else capability)
    return carried


def thinking_effort(spec: AgentSpec) -> ThinkingEffort | Literal[True] | None:
    """The `thinking` binding as a realtime setting: its effort, `True` for the provider default, `None` unbound."""
    binding = next((b for b in spec.capabilities if b.id == "thinking" and b.enabled), None)
    if binding is None:
        return None
    effort = ThinkingConfig.model_validate(binding.config).effort
    return True if effort is None else effort


def voice_unavailable(spec: AgentSpec) -> list[str]:
    """The enabled capabilities a call cannot use, by id, for the Builder to list."""
    return sorted(
        binding.id
        for binding in spec.capabilities
        if binding.enabled and not capability_def(binding.id).voice
    )


def without_voice_unavailable(spec: AgentSpec) -> AgentSpec:
    """This spec with nothing a call cannot run: stripped before the run is assembled.

    Before, not only in the factory, because `_assemble` acts on the bindings
    first - it opens a sandbox workspace and resolves delegates - and a call
    must not open a container or a delegation it can never use.
    """
    unavailable = set(voice_unavailable(spec))
    return spec.model_copy(
        update={
            "capabilities": [b for b in spec.capabilities if b.id not in unavailable],
            "subagents": [],
        }
    )
