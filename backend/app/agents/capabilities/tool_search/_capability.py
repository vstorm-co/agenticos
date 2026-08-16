"""Finding a tool instead of carrying every schema.

Pydantic AI's own `ToolSearch` is returned rather than wrapped. A capability of
ours around it would only be a second place for the same behaviour to live, and
it already does the whole job: it hides tools marked `defer_loading=True` from
the model until the model discovers them - natively where the provider offers it
(Anthropic BM25/regex, OpenAI server-side), or through a local `search_tools`
function everywhere else.

This module exists anyway, holding the one function that builds it, so the
package has the same shape as every other capability: `__init__.py` registers,
`_capability.py` builds. A reader looking for what `tool_search` *does* finds it
where the other capabilities put it.

Why it needs no metering, unlike most things that touch the model. The two local
strategies offered here - `auto`'s keyword fallback and `keywords` - run in
Python and spend no tokens; the native strategies run inside the provider's own
request, whose usage the budget guard already meters; and the `search_tools`
round-trips are ordinary model requests the same guard wraps. The one shape that
*would* escape the guard - a custom search callable that itself calls a model or
an embedding - is deliberately not exposed: the config offers named strategies
only, so there is nothing here for the budget to miss (#16 is the live example
of what forgetting this costs).
"""

from __future__ import annotations

from typing import Literal

from pydantic_ai.capabilities import ToolSearch, ToolSearchStrategy

# "auto" is the library's own `None`: native tool search where the provider
# offers it, local keyword matching everywhere else. Kept as an explicit value
# rather than an absent one so the Builder's picker always has something to show.
Strategy = Literal["auto", "keywords", "bm25", "regex"]


def build_tool_search(strategy: Strategy, max_results: int) -> ToolSearch[object]:
    """Turn a chosen strategy into the capability that carries it.

    `auto` maps to the library's `None` - let Pydantic AI pick native on a
    provider that supports it and fall back to the local keyword algorithm
    otherwise. The named strategies pass straight through: `keywords` always runs
    locally, and `bm25`/`regex` force an Anthropic-native algorithm and raise at
    request time on a provider that cannot honour them - a run-time cost the
    author accepts by naming one, since the model is resolved separately and this
    capability cannot see it at publish.
    """
    named: ToolSearchStrategy[object] | None = None if strategy == "auto" else strategy
    return ToolSearch(strategy=named, max_results=max_results)
