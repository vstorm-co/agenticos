"""Searching the public web, through whichever service the agent was given.

Four providers behind one payload. The payload is the point: every provider
returns the same `WebSearchResults` JSON, so the chat renders clickable titles
and domains whoever did the searching, and swapping Tavily for Brave is a
dropdown rather than a change to how results look.

Which one to use is a real decision, not a preference:

- **DuckDuckGo** needs no key and no account. It is the default because an
  agent that can search on the day it is created is worth more than one that
  waits for somebody to sign up for an API.
- **Tavily** is built for agents - results come back summarised rather than as
  raw snippets, which is what you want when the model is the reader.
- **Brave** runs an index of its own rather than reselling one, which matters
  if you care where the answers come from.
- **Exa** searches by meaning rather than keywords; better for "find companies
  doing X", worse for "what does Y cost".

Provider-native search - the model provider doing the searching itself - is not
here. It is not an HTTP call we make; it is a capability the model runs with, so
it lives in `_capability.py` as Pydantic AI's own `WebSearch`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

SearchProvider = Literal["duckduckgo", "tavily", "brave", "exa"]

# Long enough for a slow index, short enough that a hung search does not hold a
# conversation open while somebody watches a spinner.
_TIMEOUT_SECONDS = 15.0

# What a snippet is trimmed to. Ten results at full length is most of a small
# model's context spent on text it will quote two sentences of.
_SNIPPET_CHARS = 1000


class WebSearchResult(BaseModel):
    """A single web search hit, as every provider is normalised into."""

    title: str
    url: str
    content: str
    score: float | None = None


class WebSearchResults(BaseModel):
    """Structured web search payload returned by the `web_search` tool."""

    kind: Literal["web_search"] = "web_search"
    query: str
    provider: SearchProvider = "duckduckgo"
    results: list[WebSearchResult] = Field(default_factory=list)


class SearchUnavailable(Exception):
    """The provider cannot be reached, or was never configured.

    Raised rather than returned, so the caller decides what the model sees: an
    error in the same shape as a successful search is one the model reads as
    "nothing was found".
    """


async def search(
    query: str,
    *,
    provider: SearchProvider,
    api_key: str | None,
    max_results: int,
) -> WebSearchResults:
    """Run one search and normalise it.

    Raises:
        SearchUnavailable: If the provider needs a key it does not have, its
            package is missing, or the request failed.
    """
    capped = max(1, min(max_results, 10))
    if provider == "duckduckgo":
        results = await _duckduckgo(query, capped)
    elif provider == "tavily":
        results = await _tavily(query, capped, _require_key(api_key, "Tavily"))
    elif provider == "brave":
        results = await _brave(query, capped, _require_key(api_key, "Brave Search"))
    else:
        results = await _exa(query, capped, _require_key(api_key, "Exa"))
    return WebSearchResults(query=query, provider=provider, results=results)


def _require_key(api_key: str | None, name: str) -> str:
    if not api_key:
        raise SearchUnavailable(
            f"{name} needs an API key. Select one in the agent's web search settings."
        )
    return api_key


def _hit(title: Any, url: Any, content: Any, score: Any = None) -> WebSearchResult:
    """One result, from whatever shape the provider used for it."""
    return WebSearchResult(
        title=str(title or "Untitled"),
        url=str(url or ""),
        content=str(content or "")[:_SNIPPET_CHARS],
        score=float(score) if isinstance(score, int | float) else None,
    )


async def _duckduckgo(query: str, max_results: int) -> list[WebSearchResult]:
    """The keyless default.

    The client is synchronous and does network I/O, so it runs in a worker
    thread: calling it inline would stall the event loop - and therefore every
    other conversation on the process - for as long as the search takes.
    """
    try:
        from ddgs import DDGS
    except ImportError as exc:  # pragma: no cover - shipped as a hard dependency
        raise SearchUnavailable(
            "DuckDuckGo search is unavailable: the 'ddgs' package is not installed."
        ) from exc

    # The submodule by name: `import anyio` alone does not bind `anyio.to_thread`,
    # and the attribute only resolves at runtime because something else in the
    # process imported it first.
    from anyio import to_thread

    def _run() -> list[dict[str, Any]]:
        with DDGS() as client:
            return list(client.text(query, max_results=max_results))

    try:
        rows = await to_thread.run_sync(_run)
    except Exception as exc:
        raise SearchUnavailable(f"DuckDuckGo search failed: {exc}") from exc

    return [
        _hit(row.get("title"), row.get("href") or row.get("url"), row.get("body")) for row in rows
    ]


async def _tavily(query: str, max_results: int, api_key: str) -> list[WebSearchResult]:
    """Tavily, which summarises for a reader that is a model."""
    try:
        from tavily import AsyncTavilyClient
    except ImportError as exc:
        raise SearchUnavailable(
            "Tavily search is unavailable: the 'tavily-python' package is not installed."
        ) from exc

    try:
        response = await AsyncTavilyClient(api_key=api_key).search(
            query=query, max_results=max_results
        )
    except Exception as exc:
        raise SearchUnavailable(f"Tavily search failed: {exc}") from exc

    return [
        _hit(row.get("title"), row.get("url"), row.get("content"), row.get("score"))
        for row in response.get("results", [])
    ]


async def _brave(query: str, max_results: int, api_key: str) -> list[WebSearchResult]:
    """Brave, reached over plain HTTP - the SDK adds nothing over one GET."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": max_results},
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise SearchUnavailable(f"Brave search failed: {exc}") from exc

    return [
        _hit(row.get("title"), row.get("url"), row.get("description"))
        for row in payload.get("web", {}).get("results", [])[:max_results]
    ]


async def _exa(query: str, max_results: int, api_key: str) -> list[WebSearchResult]:
    """Exa, which searches by meaning. `text` is requested so there is a snippet."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                json={
                    "query": query,
                    "numResults": max_results,
                    "contents": {"text": {"maxCharacters": _SNIPPET_CHARS}},
                },
                headers={"Content-Type": "application/json", "x-api-key": api_key},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise SearchUnavailable(f"Exa search failed: {exc}") from exc

    return [
        _hit(row.get("title"), row.get("url"), row.get("text"), row.get("score"))
        for row in payload.get("results", [])[:max_results]
    ]


def parse_web_search(result: str) -> WebSearchResults | None:
    """Parse a `web_search` tool result back into a model.

    Returns None when the result is an error or a plain string rather than a
    structured payload - the frontend and channel layers fall back to text.
    """
    try:
        payload = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "web_search":
        return None
    try:
        return WebSearchResults.model_validate(payload)
    except ValidationError:
        return None
