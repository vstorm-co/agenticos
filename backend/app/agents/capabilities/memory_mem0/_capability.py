"""Semantic memory for an agent, kept in a mem0 service rather than here.

The counterpart to `memory_files`: that one is what the agent writes down and
looks up by name, this one is what it half-remembers and finds by meaning. They
are separate capabilities because they are separate products - an agent can bind
either, both, or neither - and folding them into one binding with a mode flag is
what produced the six-field config this replaces (#1470).

There is no standing instruction block here beyond a short habit note. The facts
live in mem0 and there is no local index to inject; `recall` is a tool call, and
an agent that also binds `memory_files` gets its injected `MEMORY.md` from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.memory_mem0._toolset import Mem0Toolset

__all__ = ["MemoryMem0"]


@dataclass
class MemoryMem0(AbstractCapability[AgentDepsT]):
    """Lets an agent remember facts and recall them by meaning, through mem0.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.memory_mem0 import MemoryMem0

    agent = Agent('anthropic:claude-sonnet-4-6', capabilities=[MemoryMem0(api_key='...')])
    ```
    """

    # The resolved plaintext, for the mem0 call and nothing else: never logged,
    # never shown to the model, never in a spec.
    api_key: str = field(repr=False)
    base_url: str | None = None
    allow_personal: bool = True

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> str:
        """The habit, and only the habit.

        A model holding `recall` but no standing instruction to use it answers "I
        have nothing saved" with the fact one search away - which is the whole
        reason a semantic store feels inert on a lighter model. What it must not
        do is describe stores the run may not have; which of them `remember`
        reaches is resolved server-side and the tool says so when asked for one
        that is missing.
        """
        return (
            "You can remember things between conversations. Search your memory with "
            "`recall` before answering a question it might inform - anything about the "
            "person you are talking to, or a fact an earlier conversation may have "
            "taught you - rather than answering generically or assuming you have "
            "nothing. When you learn something durable, keep it with `remember`."
        )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The two tools, built once per instance.

        Widened to `AbstractToolset[Any]` like `knowledge` and `memory_files`: the
        toolset is concrete in `AgentDeps`, which does not unify with the
        capability's own `AgentDepsT`.
        """
        if self._toolset is None:
            self._toolset = Mem0Toolset(
                api_key=self.api_key,
                base_url=self.base_url,
                allow_personal=self.allow_personal,
            )
        return self._toolset
