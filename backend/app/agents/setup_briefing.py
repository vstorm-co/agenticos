"""What an agent is told about its own setup: what it can do here, and what it could (#2301).

"What can you do?" is the first thing most people ask an agent, and a prompt that
answers it by listing tools is wrong the moment somebody switches one on or off -
the failure being an agent confidently refusing what it can now do, or offering
what it cannot. So the answer is assembled from the spec on every build: each
capability it has, in the words the Toolbox shows, and the ones it has not, so it
can say "I cannot do that here, but whoever edits me can switch it on".

Every agent gets it, the way every agent gets a budget: an agent that does not
know what it is missing cannot point anybody at it.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability

from app.agents.capabilities import CapabilityDef, all_capabilities
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


def _summary(description: str) -> str:
    """The first sentence of a capability's description - what the Toolbox leads with.

    Said to the agent itself, so the Toolbox's "Let the agent ask..." is "Ask...".
    """
    first, _, _rest = description.partition(". ")
    first = first.rstrip(".").removeprefix("Let the agent ")
    return first[:1].upper() + first[1:] + "."


def setup_briefing(spec: AgentSpec, *, agent_id: UUID | None) -> str:
    """The section of the instructions that says what this agent can and cannot do."""
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
    where = (
        f"in the Builder, [your capabilities](/agents/{agent_id}?highlight=agent-capabilities)"
        if agent_id is not None
        else "in the Builder"
    )
    lines = [
        "# Your setup",
        "",
        "What you can do here comes from your capabilities; each brings its own tools "
        "and its own instructions. Switched on:",
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
            *(f"- **{d.name}**: {_summary(d.description)}" for d in missing),
        ]
    lines += [
        "",
        "When somebody asks what you can do, answer from the first list in plain words, "
        "with an example of each that fits what they do. When a request needs something "
        "from the second, say so plainly, do what you can without it, and say that "
        f"whoever edits you can switch it on {where}.",
    ]
    return "\n".join(lines)


@dataclass
class SetupBriefing(AbstractCapability[Any]):
    """Puts :func:`setup_briefing` in the agent's instructions.

    A string rather than a callable: the spec does not change during a run, and an
    unchanging section keeps the prompt cache's prefix whole.
    """

    text: str

    def get_instructions(self) -> str:
        return self.text
