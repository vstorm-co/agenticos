"""Giving an agent a memory of its own - a store it writes and reads across runs.

Unlike `context` (a human-authored library injected or linked, read-only to the
model), memory is the agent's *own* store: it writes named files and short facts
through tools mid-run and reads them back in a later conversation. The capability
holds only the run-invariant part of that - which of the two stores are on - and
builds the toolset that does the work; the store itself is reached through
`app.services.memory`, which opens its own session so a mid-run read or write
never rides the session the run is on (see that module).

Memory is two-tier: a shared store (one per organization+agent) and, when a run
has an identified person, that person's personal store. Reads union the two;
writes let the model choose the *tier* while the per-end-user key is derived
server-side in the factory - so a run can never reach another person's store. A
standing preamble (`get_instructions`) tells the agent how the two tiers work and
how to classify a write, the same guidance the tool descriptions carry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.memory._toolset import MemoryToolset

__all__ = ["Memory"]

# The standing note that teaches the agent its two-tier memory and how to classify
# a write. The narrowing default (personal when unsure) is stated here and defaulted
# in the tools, because a personal-to-shared misclassification exposes one person's
# note to everyone (#788).
_MEMORY_PREAMBLE = (
    "You have a two-tier memory: a shared store (organisation-wide, the same for "
    "everyone) and, when this conversation has an identified person, that person's "
    "personal store. Reading always searches both. When you save something, choose "
    "its scope: 'personal' for anything specific to this person, 'shared' only for "
    "facts true for the whole organisation, and 'personal' when you are unsure. "
    "Where there is no identified person, personal memory is unavailable and you can "
    "only save to shared."
)


@dataclass
class Memory(AbstractCapability[AgentDepsT]):
    """Lets an agent keep and recall its own memory - files and/or facts.

    Attached only when at least one store is enabled; the builder returns `None`
    when both are off, so an agent with memory switched off carries no memory
    tools. The two stores are independent: an agent can have named files, semantic
    facts, or both. Both are two-tier - shared and, per run, the current person's -
    and the tier is resolved per operation, not fixed on the capability.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.memory import Memory

    agent = Agent('anthropic:claude-sonnet-4-6', capabilities=[Memory(enable_files=True)])
    ```
    """

    enable_files: bool = True
    enable_facts: bool = False
    # Where facts live. `native` is this deployment's pgvector; `mem0` sends them
    # to a mem0 service, and then `mem0_api_key`/`mem0_base_url` are set from the
    # binding's secret and config. Files are always native. The key is the
    # resolved plaintext (never a spec, never logged, never shown to the model);
    # the toolset uses it for the mem0 HTTP call and nothing else.
    backend: str = "native"
    mem0_base_url: str | None = None
    mem0_api_key: str | None = field(default=None, repr=False)

    # `AbstractToolset[Any]`, like `knowledge`: the toolset is concrete in
    # `AgentDeps` (its tools read `AgentDeps` fields), which does not unify with
    # the capability's own `AgentDepsT`, so the return is widened here.
    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> str | None:
        """A standing note on how the two-tier memory works and how to classify a write.

        Present whenever memory is - the builder attaches the capability only when a
        store is on - so the model reads the shared/personal split and the narrowing
        default before its first tool call, not only in each tool's own description.
        """
        return _MEMORY_PREAMBLE

    def get_toolset(self) -> AbstractToolset[Any]:
        """The memory tools this agent's config asks for, built once per instance."""
        if self._toolset is None:
            self._toolset = MemoryToolset(
                enable_files=self.enable_files,
                enable_facts=self.enable_facts,
                backend=self.backend,
                mem0_base_url=self.mem0_base_url,
                mem0_api_key=self.mem0_api_key,
            )
        return self._toolset
