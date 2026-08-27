"""The tools the knowledge capability exposes."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.capabilities.knowledge._search import search_knowledge_base
from app.agents.deps import AgentDeps

logger = logging.getLogger(__name__)


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
                top_k=top_k or default_top_k,
            )
        except Exception:
            # A retry rather than a returned message: an error in the shape of a
            # result reads as "nothing found", and the model then answers from
            # memory - confidently, and without saying it had to.
            logger.exception("knowledge_search_failed")
            return steer(ctx, "Knowledge base temporarily unavailable, please try again.")

    toolset: FunctionToolset[AgentDeps] = FunctionToolset()
    toolset.add_function(search_documents, takes_ctx=True)
    return toolset
