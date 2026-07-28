"""The tool the model is offered, and the text it reads before calling it.

One tool whatever the provider is. The provider and the key are closed over
rather than taken as arguments: they are configuration, and anything in the
signature is something the model can choose — it would pick the expensive
provider, or invent a key.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import ModelRetry
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities.web_research._search import (
    SearchProvider,
    SearchUnavailable,
    search,
)


def build_toolset(
    *, provider: SearchProvider, api_key: str | None, max_results: int
) -> FunctionToolset[Any]:
    """A `web_search` tool bound to one provider."""

    async def web_search(query: str) -> str:
        """Search the public web for current information.

        Use for facts that change or post-date your training: prices, news,
        release versions, who currently holds a role.

        Args:
            query: The search query.

        Returns:
            Titles, URLs and snippets of the top results, as JSON. Cite the
            titles and URLs in your answer; do not repeat the JSON back.
        """
        try:
            results = await search(
                query, provider=provider, api_key=api_key, max_results=max_results
            )
        except SearchUnavailable as exc:
            # `ModelRetry` rather than a returned string: an error in the shape
            # of a result is one the model reads as "nothing found", and it then
            # answers from memory — confidently, and without saying it had to.
            raise ModelRetry(str(exc)) from exc
        return results.model_dump_json()

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(web_search, takes_ctx=False)
    return toolset
