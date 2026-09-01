"""Giving an agent a memory of its own - a store it writes and reads across runs.

Unlike `context` (a human-authored library injected or linked, read-only to the
model), memory is the agent's *own* store: it writes named files and short facts
through tools mid-run and reads them back in a later conversation. The capability
holds only the run-invariant part of that - which partition to use and which of
the two stores are on - and builds the toolset that does the work; the store
itself is reached through `app.services.memory`, which opens its own session so a
mid-run read or write never rides the session the run is on (see that module).

The partition is `shared` (one store per organization+agent, for a single
trusted audience) or `per_user` (a private store per end-user). The model never
chooses it - it is fixed here from the agent's config, and the per-end-user key
is derived server-side in the factory - so a run can only ever reach the store
it was admitted to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.memory._toolset import MemoryToolset

__all__ = ["Memory"]


@dataclass
class Memory(AbstractCapability[AgentDepsT]):
    """Lets an agent keep and recall its own memory - files and/or facts.

    Attached only when at least one store is enabled; the builder returns `None`
    when both are off, so an agent with memory switched off carries no memory
    tools. The two stores are independent: an agent can have named files, semantic
    facts, or both.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.memory import Memory

    agent = Agent('anthropic:claude-sonnet-4-6', capabilities=[Memory(partition='shared')])
    ```
    """

    partition: str = "shared"
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

    def get_toolset(self) -> AbstractToolset[Any]:
        """The memory tools this agent's config asks for, built once per instance."""
        if self._toolset is None:
            self._toolset = MemoryToolset(
                partition=self.partition,
                enable_files=self.enable_files,
                enable_facts=self.enable_facts,
                backend=self.backend,
                mem0_base_url=self.mem0_base_url,
                mem0_api_key=self.mem0_api_key,
            )
        return self._toolset
