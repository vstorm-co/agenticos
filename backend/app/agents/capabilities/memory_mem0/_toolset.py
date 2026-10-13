"""The two tools the mem0 capability exposes to a running agent.

Semantic memory, and nothing else: `remember` keeps a short self-contained
sentence, `recall` finds the ones a question is about by meaning rather than by
name. Where `memory_files` is the agent's filing cabinet, this is the thing it
half-remembers and can look up.

Nothing is stored in this deployment's database. The namespace mem0 is given is
`{org}:{agent}:{owner}`, built from the run's audience, so which memories a run
can reach obeys exactly the rule the file store obeys - a person's only where
that person is the sole listener, a room's only inside that room.
"""

from __future__ import annotations

from uuid import UUID

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.audience import RunAudience
from app.agents.capabilities.memory_mem0._client import mem0_recall, mem0_remember
from app.agents.deps import AgentDeps
from app.agents.memory_scope import memory_owner_key

# A refusal the model reads as a result, not a retry: a conversation with no
# memory is not a mistake it can correct by calling again.
_NO_STORE = (
    "This conversation has no memory. It has no identified person and is not a group "
    "chat, so anything remembered would have to land somewhere other people read. "
    "Answer from what you have rather than saving."
)

# The model supplies `recall`'s `limit`; uncapped it would reach mem0 directly.
_MAX_RECALL_LIMIT = 50


class Mem0Toolset(FunctionToolset[AgentDeps]):
    """Remember and recall facts by meaning, against a mem0 service.

    Concrete in `AgentDeps` for the reason the file toolset is: every tool reads
    the run's audience and ids off `ctx.deps`, which a generic dep type could not
    name. The API key is held here as resolved plaintext for the HTTP call and
    nothing else - never logged, never shown to the model, never in a spec.
    """

    def __init__(self, *, api_key: str, base_url: str | None, allow_personal: bool) -> None:
        super().__init__()
        self._api_key = api_key
        self._base_url = base_url
        self._allow_personal = allow_personal
        self.add_function(self.remember, name="remember")
        self.add_function(self.recall, name="recall")

    def _scope(self, ctx: RunContext[AgentDeps]) -> tuple[UUID, UUID, str] | str:
        """(organization_id, agent_id, owner_key), or a refusal.

        The same rule the note store keeps, and the same single store: whichever
        one this conversation has. A run with neither a person nor a room has no
        memory at all, which is the honest answer for an anonymous visitor rather
        than a shared bucket to write into.
        """
        deps = ctx.deps
        audience = deps.audience or RunAudience()
        owner_key = memory_owner_key(audience, allow_personal=self._allow_personal)
        if deps.organization_id is None or deps.agent_id is None or owner_key is None:
            return _NO_STORE
        return deps.organization_id, deps.agent_id, owner_key

    async def remember(self, ctx: RunContext[AgentDeps], content: str) -> str:
        """Remember a fact you will want to recall later by its meaning.

        Use this for something durable you learned - a preference, a decision, a
        fact about this person or subject - that a future conversation should be
        able to find without knowing the exact words. Do not store secrets, or
        anything the person would not expect you to keep. Facts are found with
        `recall`, not by name.

        Args:
            content: The fact to remember, as a short, self-contained sentence.

        Returns:
            A confirmation. It is kept in this conversation's own memory - one
            person's when you are alone with them, this group chat's when you are
            not.
        """
        scope = self._scope(ctx)
        if isinstance(scope, str):
            return scope
        organization_id, agent_id, owner_key = scope
        await mem0_remember(
            base_url=self._base_url,
            api_key=self._api_key,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            content=content,
        )
        return "Remembered."

    async def recall(self, ctx: RunContext[AgentDeps], query: str, limit: int = 5) -> str:
        """Recall facts relevant to a question, by meaning rather than exact words.

        Use this before answering anything a past conversation may have taught you
        about this person or subject. Weigh what comes back against the current
        conversation - it is your own past notes, not ground truth.

        Args:
            query: What you are trying to remember, phrased as you would ask it.
            limit: How many facts to return at most. Omit for a sensible default.

        Returns:
            The most relevant facts, most-relevant first, or a line saying none
            were found.
        """
        scope = self._scope(ctx)
        if isinstance(scope, str):
            return scope
        organization_id, agent_id, owner_key = scope
        hits = await mem0_recall(
            base_url=self._base_url,
            api_key=self._api_key,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            query=query,
            limit=min(max(limit, 1), _MAX_RECALL_LIMIT),
        )
        if not hits:
            return "No relevant memories."
        return "\n".join(f"- {hit.content}" for hit in hits)
