"""Tests for web search across the providers an agent can be given.

The properties worth guarding are the ones a provider swap could break: every
service normalises into the same payload the chat renders, a missing key is
refused before a request goes anywhere, and a failure reaches the model as a
retryable error rather than as an empty result - which it would otherwise
answer around, confidently, without saying so.
"""

import json
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities._registry import CapabilityBinding, build, get
from app.agents.capabilities.web_research import KEYED_METHODS, WebResearch, WebResearchConfig
from app.agents.capabilities.web_research._search import (
    SearchUnavailable,
    WebSearchResults,
    parse_web_search,
    search,
)
from app.core.secret_kinds import ApiKeySecret


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
            pytest.raises(SearchUnavailable, match="rate limited"),
        ):
            await search("q", provider="tavily", api_key="k", max_results=5)

    @pytest.mark.anyio
    async def test_the_tool_asks_the_model_to_retry_instead_of_answering_from_memory(self):
        from pydantic_ai import ModelRetry

        from app.agents.capabilities.web_research._toolset import build_toolset

        toolset = build_toolset(provider="tavily", api_key=None, max_results=5)
        with pytest.raises(ModelRetry):
            await toolset.tools["web_search"].function(query="x")


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
