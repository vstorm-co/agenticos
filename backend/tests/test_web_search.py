"""Tests for web search across the providers an agent can be given.

The properties worth guarding are the ones a provider swap could break: every
service normalises into the same payload the chat renders, a missing key is
refused before a request goes anywhere, and a failure reaches the model as a
retryable error rather than as an empty result - which it would otherwise
answer around, confidently, without saying so.
"""

import json
import logging
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities._registry import CapabilityBinding, build, get
from app.agents.capabilities.web_research import KEYED_METHODS, WebResearch, WebResearchConfig
from app.agents.capabilities.web_research._search import (
    SearchUnavailable,
    WebSearchResults,
    parse_web_search,
    search,
)
from app.core.secret_kinds import ApiKeySecret


@pytest.fixture(autouse=True)
def _reset_search_client():
    """The HTTP providers share one client (#1263); reset it so each test's
    `httpx.AsyncClient` patch is what the next `search()` builds."""
    from app.agents.capabilities.web_research import _search

    _search._client = None
    yield
    _search._client = None


def _tool_ctx(*, retry: int = 0, max_retries: int = 1) -> RunContext[None]:
    """A context with a retry left, which is what a real call starts with."""
    return RunContext(
        deps=None, model=TestModel(), usage=RunUsage(), retry=retry, max_retries=max_retries
    )


def _tavily_module(response: dict | Exception) -> MagicMock:
    client = MagicMock()
    client.search = (
        AsyncMock(side_effect=response)
        if isinstance(response, Exception)
        else AsyncMock(return_value=response)
    )
    module = MagicMock()
    module.AsyncTavilyClient = MagicMock(return_value=client)
    return module


def _http_client(method: str, payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    client = MagicMock()
    setattr(client, method, AsyncMock(return_value=response))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestProviderNormalisation:
    """Four services, one payload - that is what keeps the chat rendering."""

    @pytest.mark.anyio
    async def test_tavily_results_become_the_common_shape(self):
        module = _tavily_module(
            {
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com",
                        "content": "text",
                        "score": 0.9,
                    }
                ]
            }
        )
        with patch.dict(sys.modules, {"tavily": module}):
            results = await search("q", provider="tavily", api_key="k", max_results=5)

        assert results.provider == "tavily"
        assert results.results[0].url == "https://example.com"
        assert results.results[0].score == 0.9

    @pytest.mark.anyio
    async def test_brave_uses_its_own_field_names(self):
        """Brave calls the snippet `description`; the payload must not care."""
        client = _http_client(
            "get",
            {
                "web": {
                    "results": [{"title": "T", "url": "https://b.dev", "description": "snippet"}]
                }
            },
        )
        with patch("httpx.AsyncClient", return_value=client):
            results = await search("q", provider="brave", api_key="k", max_results=5)

        assert results.results[0].content == "snippet"

    @pytest.mark.anyio
    async def test_exa_uses_text_for_the_snippet(self):
        client = _http_client(
            "post",
            {"results": [{"title": "T", "url": "https://e.dev", "text": "body", "score": 0.4}]},
        )
        with patch("httpx.AsyncClient", return_value=client):
            results = await search("q", provider="exa", api_key="k", max_results=5)

        assert results.results[0].content == "body"

    @pytest.mark.anyio
    async def test_duckduckgo_needs_no_key_at_all(self):
        """The default, and the reason it is the default."""
        client = MagicMock()
        client.text = MagicMock(
            return_value=[{"title": "T", "href": "https://d.dev", "body": "snippet"}]
        )
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        module = MagicMock()
        module.DDGS = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"ddgs": module}):
            results = await search("q", provider="duckduckgo", api_key=None, max_results=5)

        assert results.results[0].url == "https://d.dev"

    @pytest.mark.anyio
    async def test_a_provider_that_needs_a_key_refuses_before_the_request(self):
        with pytest.raises(SearchUnavailable, match="Tavily needs an API key"):
            await search("q", provider="tavily", api_key=None, max_results=5)


class TestFailures:
    @pytest.mark.anyio
    async def test_a_failing_provider_raises_rather_than_returning_nothing(self):
        """An error shaped like a result is one the model reads as "no hits"."""
        with (
            patch.dict(sys.modules, {"tavily": _tavily_module(RuntimeError("429 rate limited"))}),
            pytest.raises(SearchUnavailable, match="Tavily search is unavailable"),
        ):
            await search("q", provider="tavily", api_key="k", max_results=5)

    @pytest.mark.anyio
    async def test_a_providers_own_message_stays_in_the_log(self, caplog):
        """The vendor's text names the failing endpoint, and an SDK puts the key in
        its query string. On the model's last attempt `steer` returns this message
        rather than raising it, and a returned string is stored and streamed whole -
        so only the exception's class travels and the rest goes to the log.
        """
        vendor_text = "401 for url 'https://api.tavily.com/search?k=sk-9f2c'"
        module = _tavily_module(RuntimeError(vendor_text))
        with (
            caplog.at_level(logging.ERROR, logger="app.agents.capabilities.web_research._search"),
            patch.dict(sys.modules, {"tavily": module}),
            pytest.raises(SearchUnavailable) as raised,
        ):
            await search("q", provider="tavily", api_key="k", max_results=5)

        assert str(raised.value) == (
            "Tavily search is unavailable (RuntimeError). The server log has the full error."
        )
        assert vendor_text not in str(raised.value)
        assert vendor_text in caplog.text

    @pytest.mark.anyio
    async def test_the_tool_asks_the_model_to_retry_instead_of_answering_from_memory(self):
        from pydantic_ai import ModelRetry

        from app.agents.capabilities.web_research._toolset import build_toolset

        toolset = build_toolset(provider="tavily", api_key=None, max_results=5)
        with pytest.raises(ModelRetry):
            await toolset.tools["web_search"].function(_tool_ctx(), query="x")

    @pytest.mark.anyio
    async def test_the_last_attempt_says_so_rather_than_ending_the_run(self):
        """A `ModelRetry` past the budget takes the conversation with it."""
        from app.agents.capabilities.web_research._toolset import build_toolset

        toolset = build_toolset(provider="tavily", api_key=None, max_results=5)

        answered = await toolset.tools["web_search"].function(_tool_ctx(retry=1), query="x")

        assert "tavily" in answered.lower()


class TestConfiguration:
    def test_the_default_is_the_one_that_works_with_no_account(self):
        assert WebResearchConfig().method == "duckduckgo"

    def test_a_keyless_method_publishes_without_a_secret(self):
        """The point of the conditional requirement: the free default stays usable."""
        definition = get("web_research")
        assert definition.needs_secret(WebResearchConfig(method="duckduckgo")) is False
        assert definition.needs_secret(WebResearchConfig(method="native")) is False

    def test_a_capability_that_declares_no_key_never_asks_for_one(self):
        """Most builtins take no credential at all. The same question is asked of
        every capability the Builder shows, so this answer is the common case -
        and one that returned True would make every agent unpublishable."""
        assert get("thinking").needs_secret(None) is False

    @pytest.mark.parametrize("method", sorted(KEYED_METHODS))
    def test_a_paid_service_must_name_a_key(self, method: str):
        assert get("web_research").needs_secret(WebResearchConfig(method=method)) is True

    def test_the_chosen_provider_reaches_the_capability(self):
        secret_id = uuid.uuid4()
        built = build(
            [
                CapabilityBinding(
                    capability_id="web_research",
                    config={"method": "brave"},
                    secret_id=secret_id,
                )
            ],
            secrets={secret_id: ApiKeySecret(api_key="brave-key")},
        )
        capability = built[0]
        assert isinstance(capability, WebResearch)
        assert capability.provider == "brave"

    def test_native_search_hands_the_job_to_the_model_provider(self):
        """No key of ours and no payload of ours - Pydantic AI's own capability."""
        from pydantic_ai.capabilities import WebSearch

        built = build(
            [CapabilityBinding(capability_id="web_research", config={"method": "native"})]
        )
        assert isinstance(built[0], WebSearch)

    def test_the_key_is_unsealed_into_the_capability_and_nowhere_else(self):
        secret_id = uuid.uuid4()
        built = build(
            [
                CapabilityBinding(
                    capability_id="web_research",
                    config={"method": "tavily"},
                    secret_id=secret_id,
                )
            ],
            secrets={secret_id: ApiKeySecret(api_key="tvly-secret")},
        )
        capability = built[0]
        assert isinstance(capability, WebResearch)
        assert capability.api_key == "tvly-secret"
        # Not in the repr, which is what ends up in a log line or a traceback.
        assert "tvly-secret" not in repr(capability)


class TestParsing:
    def test_round_trip(self):
        payload = WebSearchResults(query="q", provider="brave").model_dump_json()
        assert parse_web_search(payload) is not None
        assert json.loads(payload)["kind"] == "web_search"

    def test_non_json_returns_none(self):
        assert parse_web_search("Web search failed: boom") is None

    def test_wrong_kind_returns_none(self):
        assert parse_web_search('{"kind": "chart"}') is None


class TestSharedHttpClient:
    """The HTTP-based providers reuse one client rather than opening one per call
    (#1263), and it is closed at shutdown."""

    @pytest.mark.anyio
    async def test_the_client_is_built_once_and_reused(self):
        from app.agents.capabilities.web_research import _search

        made = 0

        def _make(**_kwargs: object) -> MagicMock:
            nonlocal made
            made += 1
            return MagicMock(is_closed=False)

        with patch("httpx.AsyncClient", _make):
            first = _search._http()
            second = _search._http()

        assert made == 1
        assert first is second

    @pytest.mark.anyio
    async def test_a_closed_client_is_rebuilt(self):
        from app.agents.capabilities.web_research import _search

        _search._client = MagicMock(is_closed=True)
        fresh = MagicMock(is_closed=False)
        with patch("httpx.AsyncClient", MagicMock(return_value=fresh)):
            assert _search._http() is fresh

    @pytest.mark.anyio
    async def test_close_closes_a_live_client(self):
        from app.agents.capabilities.web_research import _search

        client = MagicMock(is_closed=False, aclose=AsyncMock())
        _search._client = client
        await _search.close_http_client()
        client.aclose.assert_awaited_once()
        assert _search._client is None

    @pytest.mark.anyio
    async def test_close_skips_an_already_closed_client_and_a_missing_one(self):
        from app.agents.capabilities.web_research import _search

        already = MagicMock(is_closed=True, aclose=AsyncMock())
        _search._client = already
        await _search.close_http_client()
        already.aclose.assert_not_awaited()
        assert _search._client is None
        # And a no-op when there is nothing to close.
        await _search.close_http_client()
        assert _search._client is None
