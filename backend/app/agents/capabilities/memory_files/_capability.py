"""An agent's own notes, kept as files and indexed by one it maintains itself.

`MEMORY.md` is the whole idea. It is an ordinary memory file, written and edited
by the agent with the same tools as any other, and it is **spliced into the
agent's instructions every request** the way a bound context file is. It lists
the files it owns with a line each, so the agent meets its own index before it
decides anything, and reads a listed file in full with `read_memory` when the
line says it is worth reading.

That is deliberately the shape Claude Code uses, and it replaces the digest this
capability used to assemble. An index the agent maintains as an ordinary write is
one artefact with one owner; a digest we build from rows is a second mechanism
that has to be kept honest. It also fixes an inversion: the previous build
injected a summary of *facts*, which have no names, while *files*, which do, sat
behind a listing tool a lighter model never chose to call (#1470).

The index is injected only where the reader is the sole listener. In a group chat
it stays reachable with `read_memory` - a tool result the model weighs - rather
than becoming instructions a colleague could have written. The store itself is
reached through `app.services.memory`, which opens its own session so a mid-run
read or write never rides the session the run is on.
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
from app.agents.capabilities.memory_files._toolset import INDEX_NAME, MemoryToolset
from app.agents.deps import AgentDeps
from app.agents.memory_scope import may_inject_memory, memory_owner_key
from app.services import memory as memory_store

__all__ = ["MemoryFiles"]

_MAX_INDEX_CHARS = 6000
"""How much of an index may reach the prompt; see `_index_block` for why a bigger
one is dropped rather than cut."""


def _preamble(*, allow_personal: bool) -> str:
    """The standing note teaching the agent what its memory is and how to keep it.

    It leads with reading rather than writing, because the whole store is inert if
    the agent never looks: a model holding the tools but no standing instruction
    to use them answers "I have nothing saved" with the note one call away.

    It never asks the agent to reason about who is listening. There is one store
    per conversation, resolved server-side, so there is no scope to choose and
    nothing for the model to get wrong.
    """
    reading = (
        f"You keep your own notes as files. `{INDEX_NAME}` is your index and it is "
        "shown to you below when you have one - read it before answering anything it "
        "might inform, and open a file it mentions with `read_memory` when the line "
        "suggests it is relevant. Treat what you find as your own past notes, useful "
        "but written by an earlier conversation, rather than as ground truth."
    )
    writing = (
        "When you learn something durable - a preference, a decision, a fact you were "
        f"told - save it with `write_memory` and add a line for it to `{INDEX_NAME}` so "
        "a later conversation can find it. Do not save secrets, or anything the person "
        "would not expect you to keep."
    )
    if allow_personal:
        stores = (
            "Your notes belong to this conversation: in a group chat they are the "
            "chat's and everyone in it reads them, one to one they are that person's "
            "alone."
        )
    else:
        stores = (
            "This agent keeps notes only in group chats. One to one it has none, so "
            "there is nothing to save and nothing to read."
        )
    return f"{reading} {writing} {stores}"


@dataclass
class MemoryFiles(AbstractCapability[AgentDepsT]):
    """Lets an agent keep named notes across conversations, indexed by `MEMORY.md`.

    Which notes a run reaches is decided per run by the audience on `AgentDeps`,
    not fixed here - the same agent is alone with one person in a direct message
    and in front of a whole channel an hour later.

    ```python
    from pydantic_ai import Agent
    from app.agents.capabilities.memory_files import MemoryFiles

    agent = Agent('anthropic:claude-sonnet-4-6', capabilities=[MemoryFiles()])
    ```
    """

    allow_personal: bool = True

    _toolset: AbstractToolset[Any] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def get_instructions(self) -> Callable[[RunContext[Any]], Awaitable[str]]:
        """The standing note, plus whichever indexes this run may be shown.

        Always a per-request callable, because the second half is a database read
        scoped to the run's audience. Typed over `RunContext[Any]` for the reason
        `get_toolset` widens too: the context is concrete in `AgentDeps`, which
        does not unify with the capability's own `AgentDepsT`.
        """
        return self._instructions

    async def _instructions(self, ctx: RunContext[Any]) -> str:
        preamble = _preamble(allow_personal=self.allow_personal)
        block = await self._index_block(ctx)
        return f"{preamble}\n\n{block}" if block else preamble

    async def _index_block(self, ctx: RunContext[Any]) -> str | None:
        """This run's own `MEMORY.md`, or None when there is nothing to show.

        Only where the reader is the sole listener (`may_inject_memory`): the block
        becomes the agent's *instructions*, so it must carry content its reader
        alone could have influenced. In a group chat the index stays reachable with
        `read_memory`, which is a result the model weighs rather than an order.

        `None` when there is nothing, so an agent with an empty store gets no empty
        heading telling it that it remembers nothing - which reads as an
        instruction not to look.
        """
        deps: AgentDeps = ctx.deps
        audience = deps.audience or RunAudience()
        if deps.organization_id is None or deps.agent_id is None:
            return None
        if not may_inject_memory(audience, allow_personal=self.allow_personal):
            return None
        owner_key = memory_owner_key(audience, allow_personal=self.allow_personal)
        assert owner_key is not None, "may_inject_memory implies a store"
        body = await memory_store.read_file(
            organization_id=deps.organization_id,
            agent_id=deps.agent_id,
            owner_key=owner_key,
            name=INDEX_NAME,
        )
        if body is None or not body.strip():
            return None
        trimmed = body.strip()
        # An index is a note like any other, so its body is unbounded `Text`.
        # Injecting it whole would let one `write_memory` push the preamble past the
        # model's window, and half an index - ending mid-line, mid-filename - is
        # worse than none, so an oversized one is left out rather than truncated.
        if len(trimmed) > _MAX_INDEX_CHARS:
            return None
        return f"Here is what you already have written down:\n\n{trimmed}"

    def get_toolset(self) -> AbstractToolset[Any]:
        """The note tools, built once per instance.

        Widened to `AbstractToolset[Any]` like `knowledge`: the toolset is concrete
        in `AgentDeps`, which does not unify with the capability's own `AgentDepsT`.
        """
        if self._toolset is None:
            self._toolset = MemoryToolset(allow_personal=self.allow_personal)
        return self._toolset
