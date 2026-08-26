"""The tools the knowledge capability exposes."""

from __future__ import annotations

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.deps import AgentDeps


def build_knowledge_toolset(*, default_top_k: int) -> FunctionToolset[AgentDeps]:
    """A toolset with one search tool, under the name it is declared with.

    The same search is "Search orders" for one agent and "Look up policies" for
    another - but that is said in the binding's `tool_overrides`, applied for
    every capability at once, not here. A rename this toolset performed itself
    would be invisible to the approval gate.
    """

    async def search_documents(
        ctx: RunContext[AgentDeps], query: str, top_k: int | None = None
    ) -> str:
        """Search the organization's documents for passages relevant to a question.

        Use before answering anything that depends on internal knowledge, and
        cite the document names from the results rather than paraphrasing.

        Args:
            query: What to look for, phrased as the user would ask it.
            top_k: How many passages to return. Omit to use the agent's default.

        Returns:
            Formatted passages with their source documents and relevance scores.
        """
        try:
            return await search_knowledge_base(
                query=query,
                # Resolved server-side from the agent's bound collections. The
                # model chooses *what* to search, never *where*.
                kb_collection_names=ctx.deps.kb_collection_names,
                # The bound knowledge base ids, aligned with the names, so a
                # shared collection name resolves the bound row's config and key
                # rather than another same-named row's (#913).
                kb_collection_ids=ctx.deps.kb_collection_ids,
                top_k=top_k or default_top_k,
                # The run's own organization, so a collection name shared with
                # another tenant resolves this agent's config, not theirs (#913).
                organization_id=ctx.deps.organization_id,
            )
        except Exception as exc:
            raise ModelRetry("Knowledge base temporarily unavailable, please try again.") from exc

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(search_documents, takes_ctx=True)
    return toolset
