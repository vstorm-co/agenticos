"""Search over the past conversations of whoever the run is answering.

The counterpart to `memory_files`: that one is what the agent chose to write down,
this one is everything that was actually said. An agent with memory alone can only
recall what a past turn thought worth saving, which is why "what did we decide
about the pricing" answers "I have no record of that" in a product that has the
whole exchange on disk (#789).

There is no index to inject and nothing standing to add to every request. The
corpus is the person's, resolved per run from the audience, and the instruction is
one sentence telling the agent the tools exist - a model holding a search tool but
no standing note to use it answers from what is in front of it, confidently.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.audience import RunAudience
from app.agents.capabilities.conversation_search._toolset import ConversationSearchToolset
from app.agents.deps import AgentDeps

__all__ = ["ConversationSearch"]

_HABIT = (
    "You can search the past conversations of the person you are talking to - their "
    "own, the ones shared with them, and the group chats they are in - with "
    "`search_conversations`, and open one in full with `read_conversation`. Use it "
    "before answering anything that turns on something said earlier, rather than "
    "saying you have no record of it. What you find is one person's; quote from it to "
    "them and to nobody else."
)


@dataclass
class ConversationSearch(AbstractCapability[AgentDepsT]):
    """Lets an agent find and read the past conversations of the person it answers.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.conversation_search import ConversationSearch

    agent = Agent('anthropic:claude-sonnet-4-6', capabilities=[ConversationSearch()])
    ```
    """

    max_results: int = 10

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> Callable[[RunContext[Any]], Awaitable[str]]:
        """The habit, but only where there is a corpus to have one about.

        Per-request rather than static because the tools refuse in a group chat,
        and an instruction promising a search that will be refused is worse than
        none: the model spends a call finding out. Typed over `RunContext[Any]` for
        the reason `get_toolset` widens too - the context is concrete in
        `AgentDeps`, which does not unify with the capability's own `AgentDepsT`.
        """
        return self._instructions

    async def _instructions(self, ctx: RunContext[Any]) -> str:
        deps: AgentDeps = ctx.deps
        audience = deps.audience or RunAudience()
        if audience.user_id is None or not audience.private:
            return ""
        return _HABIT

    def get_toolset(self) -> AbstractToolset[Any]:
        """The two tools, built once per instance."""
        if self._toolset is None:
            self._toolset = ConversationSearchToolset(max_results=self.max_results)
        return self._toolset
