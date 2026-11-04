"""What an agent is told about its own setup: what it can do here, and what it could (#2301).

"What can you do?" is the first thing most people ask an agent, and a prompt that
answers it by listing tools is wrong the moment somebody switches one on or off -
the failure being an agent confidently refusing what it can now do, or offering
what it cannot. So the answer is assembled from the spec on every build: each
capability it has, in the words the Toolbox shows, and the ones it has not, so it
can say "I cannot do that here" - and show the person a card that switches it on.

Every agent gets it, the way every agent gets a budget: an agent that does not
know what it is missing cannot point anybody at it.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities import CapabilityDef, all_capabilities
from app.agents.capabilities._failures import steer
from app.agents.spec import AgentSpec

PLUMBING = frozenset(
    {
        "background_tools",
        "clock",
        "compaction",
        "guardrails",
        "media",
        "system_reminders",
        "thinking",
        "tool_output_limits",
        "tool_search",
    }
)
"""Capabilities that change how an agent works rather than what it can do for
somebody. Not worth listing as an ability, nor suggesting as a missing one.

An exclusion rather than a list of what to show, so a capability added to the
registry is offered from the day it ships."""

ALTERNATIVES = (frozenset({"memory_files", "memory_mem0"}),)
"""Capabilities that are two ways of doing one thing: an agent with either is
not told it lacks the other."""

REQUEST_CAPABILITY = "request_capability"
"""The tool's name, which the console draws a card for."""


def _summary(description: str) -> str:
    """The first sentence of a capability's description - what the Toolbox leads with.

    Said to the agent itself, so the Toolbox's "Let the agent ask..." is "Ask...".
    """
    first, _, _rest = description.partition(". ")
    first = first.rstrip(".").removeprefix("Let the agent ")
    return first[:1].upper() + first[1:] + "."


def _inventory(spec: AgentSpec) -> tuple[list[CapabilityDef], list[CapabilityDef]]:
    """What the agent has, and what it could be given, in the Toolbox's order."""
    bound = {binding.id for binding in spec.capabilities if binding.enabled}
    covered = set(bound | PLUMBING)
    for group in ALTERNATIVES:
        if group & bound:
            covered |= group
    has: list[CapabilityDef] = []
    missing: list[CapabilityDef] = []
    for definition in all_capabilities():
        if definition.id in bound and definition.id not in PLUMBING:
            has.append(definition)
        elif definition.selectable and definition.id not in covered:
            missing.append(definition)
    return has, missing


def setup_briefing(spec: AgentSpec, *, agent_id: UUID | None) -> str:
    """The section of the instructions that says what this agent can and cannot do."""
    has, missing = _inventory(spec)
    lines = [
        "# Your setup",
        "",
        (
            "What you can do here comes from your capabilities; each brings its own tools "
            "and its own instructions. Switched on:"
        ),
        *(f"- **{d.name}**: {_summary(d.description)}" for d in has),
    ]
    if spec.collection_ids:
        lines.append(
            f"- **Knowledge**: {len(spec.collection_ids)} knowledge base(s) to answer from."
        )
    if spec.mcp_servers:
        lines.append(
            "- **Connected services**: the MCP tools you were given, named after the service."
        )
    if missing:
        lines += [
            "",
            "Not switched on, so you cannot do these here:",
            *(f"- **{d.name}** (`{d.id}`): {_summary(d.description)}" for d in missing),
        ]
    if agent_id is not None and missing:
        unlock = (
            f"call `{REQUEST_CAPABILITY}` with its id and why you need it: the person sees a "
            "card - one click switches it on if they may edit you, and asks your owner if not"
        )
    else:
        unlock = "say that whoever edits you can switch it on in the Builder"
    lines += [
        "",
        (
            "When somebody asks what you can do, answer from the first list in plain words, "
            "with an example of each that fits what they do. When a request needs something "
            f"from the second, say so plainly, do what you can without it, and {unlock}."
        ),
    ]
    return "\n".join(lines)


# What `CapabilityRequest.reason` accepts, which the card's button posts.
MAX_REASON_CHARS = 300


class RequestCapabilityToolset(FunctionToolset[Any]):
    """The card an agent shows for a capability it lacks."""

    def __init__(self, *, agent_id: UUID, missing: dict[str, str]) -> None:
        super().__init__()
        self._agent_id = agent_id
        self._missing = missing
        self.add_function(self.request_capability, name=REQUEST_CAPABILITY)

    def request_capability(self, ctx: RunContext[Any], capability_id: str, reason: str) -> str:
        """Show the person a card that switches on a capability you lack.

        Use it when a request needs something under "Not switched on" in your
        setup. Whoever may edit you switches it on with one click; anyone else
        asks your owner from it. Say in your answer what you would do once it is
        on, and do the rest of the request without it.

        Args:
            capability_id: Its id, as your setup lists it, e.g. `web_research`.
            reason: What you need it for, one sentence in the person's language.

        Returns:
            JSON the card is drawn from - nothing to repeat to the person.
        """
        name = self._missing.get(capability_id)
        if name is None:
            return steer(
                ctx,
                f"{capability_id!r} is not one you lack. Use an id from the "
                f'"Not switched on" list: {", ".join(sorted(self._missing))}.',
            )
        said = " ".join(reason.split())
        # The card's button posts this as `CapabilityRequest.reason`, which takes
        # 1-300 characters: a card outside them would refuse every press (Codex
        # on #2324), so the model is asked again instead.
        if not said or len(said) > MAX_REASON_CHARS:
            return steer(
                ctx,
                f"Give the reason as one sentence of at most {MAX_REASON_CHARS} characters.",
            )
        return json.dumps(
            {
                "agent_id": str(self._agent_id),
                "capability_id": capability_id,
                "name": name,
                "reason": said,
            },
            ensure_ascii=False,
        )


@dataclass
class SetupBriefing(AbstractCapability[Any]):
    """Puts :func:`setup_briefing` in the agent's instructions, and the card beside it.

    A string rather than a callable: the spec does not change during a run, and an
    unchanging section keeps the prompt cache's prefix whole. The card is offered
    only to an agent that lacks something and has an id a card can name.
    """

    text: str
    agent_id: UUID | None = None
    missing: dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_spec(cls, spec: AgentSpec, *, agent_id: UUID | None) -> SetupBriefing:
        _has, missing = _inventory(spec)
        return cls(
            text=setup_briefing(spec, agent_id=agent_id),
            agent_id=agent_id,
            missing={definition.id: definition.name for definition in missing},
        )

    def get_instructions(self) -> str:
        return self.text

    def get_toolset(self) -> RequestCapabilityToolset | None:
        if self.agent_id is None or not self.missing:
            return None
        return RequestCapabilityToolset(agent_id=self.agent_id, missing=self.missing)
