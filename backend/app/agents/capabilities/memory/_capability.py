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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import AgentDepsT
from pydantic_ai.toolsets import AbstractToolset

from app.agents.capabilities.memory._toolset import MemoryToolset
from app.agents.deps import AgentDeps
from app.services import memory as memory_store

__all__ = ["Memory"]

# The standing brief is a digest, not the store: a run that needs a fact past it
# reaches for `recall`. It is bounded twice - at most `_BRIEF_LIMIT` facts, and at
# most `_BRIEF_MAX_CHARS` of them - because a row count alone does not bound the
# injected context: a fact's content is `Text` and an operator seed runs to 2000
# characters, so enough large facts could push this per-request preamble past the
# model's window and fail every later request before `recall` could help (#788).
_BRIEF_LIMIT = 30
_BRIEF_MAX_CHARS = 4000


def _preamble(*, allow_personal: bool, allow_agent_shared_writes: bool) -> str:
    """The standing note teaching the agent to read its memory, its tiers, and how to save.

    Composed from the two operator levers so it never promises a tier the config has
    switched off: an agent told to "choose a scope" that then has every choice
    refused is worse than one told plainly what it can do. The narrowing default
    (personal when unsure) is stated here and defaulted in the tools, because a
    personal-to-shared misclassification exposes one person's note to everyone (#788).

    The reading habit leads, because the whole store is inert if the agent never
    looks: memory only pays off when a later run recalls what an earlier one saved,
    and a model with the tool but no standing instruction to use it will answer "I
    have nothing saved" while the fact sits one search away.
    """
    habit = (
        "Search your memory before answering a question it might inform - anything "
        "about the person you are talking to, a fact you may have saved in an earlier "
        "conversation, or a recommendation you could tailor to them - rather than "
        "answering generically or assuming you have nothing."
    )
    if allow_personal:
        reading = (
            "Your memory has two tiers: a shared store (organisation-wide, the same "
            "for everyone) and, when this conversation has an identified person, that "
            "person's personal store. Reading searches both."
        )
    else:
        reading = (
            "You have a shared, organisation-wide memory (the same for everyone). "
            "Reading searches it."
        )
    if allow_personal and allow_agent_shared_writes:
        writing = (
            "When you save something, choose its scope: 'personal' for anything "
            "specific to this person, 'shared' only for facts true for the whole "
            "organisation, and 'personal' when you are unsure. Where there is no "
            "identified person, only 'shared' can be saved to."
        )
    elif allow_personal:
        writing = (
            "Save what you learn to your personal memory (scope='personal'); the "
            "shared store is curated by operators and is read-only to you. Where there "
            "is no identified person, you cannot save."
        )
    elif allow_agent_shared_writes:
        writing = "Save what you learn to the shared memory (scope='shared')."
    else:
        writing = (
            "This memory is read-only to you - operators curate it - so you cannot "
            "save to it, only read."
        )
    return f"{habit} {reading} {writing}"


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
    # The two tier levers. `allow_personal` off makes the agent shared-only (no
    # per-end-user store); `allow_agent_shared_writes` off keeps the shared store
    # operator-curated - the agent reads it but may not write it. Both default on,
    # which is the plain two-tier model.
    allow_personal: bool = True
    allow_agent_shared_writes: bool = True
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

    def get_instructions(self) -> str | Callable[[RunContext[Any]], Awaitable[str]]:
        """A standing note on how this agent's memory works, and what it already holds.

        The preamble (how the tiers work, how to classify a write, to read before
        answering) is run-invariant, so a files-only or mem0-facts agent gets it as a
        plain string. A native-facts agent gets a per-request callable instead, so the
        note carries a brief of what is already remembered - the facts a run would
        otherwise have to call `recall` to see. A model with them in front of it
        answers from them; one that must decide to look usually does not, which is the
        whole reason the store felt inert on a lighter model (#788).

        The callable is typed over `RunContext[Any]` for the same reason `get_toolset`
        widens to `AbstractToolset[Any]`: the run context is concrete in `AgentDeps`
        (the brief reads its fields), which does not unify with the capability's own
        `AgentDepsT`. `_memory_brief` narrows it straight back.
        """
        if self.enable_facts and self.backend == "native":
            return self._instructions_with_brief
        return _preamble(
            allow_personal=self.allow_personal,
            allow_agent_shared_writes=self.allow_agent_shared_writes,
        )

    async def _instructions_with_brief(self, ctx: RunContext[Any]) -> str:
        preamble = _preamble(
            allow_personal=self.allow_personal,
            allow_agent_shared_writes=self.allow_agent_shared_writes,
        )
        brief = await self._memory_brief(ctx)
        return f"{preamble}\n\n{brief}" if brief else preamble

    async def _memory_brief(self, ctx: RunContext[Any]) -> str | None:
        """The facts already remembered, listed for the agent's context, or None.

        Injected every request rather than left to a `recall` the model may not make -
        the standing digest that makes memory feel present. The tier is the run's own
        read tier (shared, plus this person's when `allow_personal` and the run has a
        person), so the brief can never surface another person's note. `None` when
        there is nothing to show, so no empty heading is added.
        """
        deps: AgentDeps = ctx.deps
        if deps.organization_id is None or deps.agent_id is None:
            return None
        personal_key = deps.end_user_scope_key if self.allow_personal else None
        facts = await memory_store.memory_brief(
            organization_id=deps.organization_id,
            agent_id=deps.agent_id,
            personal_key=personal_key,
            limit=_BRIEF_LIMIT,
        )
        if not facts:
            return None
        # Bound the injected text by size, not only by row count: keep the newest
        # facts until the budget is spent. Every line is bounded, the first
        # included - a single fact past the whole budget is dropped, never spliced
        # in unbounded, so a runtime `remember` cannot blow the context window by
        # writing one enormous fact (#788, codex).
        lines: list[str] = []
        remaining = _BRIEF_MAX_CHARS
        for content in facts:
            line = f"- {content}"
            if len(line) > remaining:
                break
            lines.append(line)
            remaining -= len(line) + 1
        if not lines:
            return None
        body = "\n".join(lines)
        return (
            "Here is what you already remember - your own past notes, not ground "
            f"truth, and `recall` can search for more:\n{body}"
        )

    def get_toolset(self) -> AbstractToolset[Any]:
        """The memory tools this agent's config asks for, built once per instance."""
        if self._toolset is None:
            self._toolset = MemoryToolset(
                enable_files=self.enable_files,
                enable_facts=self.enable_facts,
                allow_personal=self.allow_personal,
                allow_agent_shared_writes=self.allow_agent_shared_writes,
                backend=self.backend,
                mem0_base_url=self.mem0_base_url,
                mem0_api_key=self.mem0_api_key,
            )
        return self._toolset
