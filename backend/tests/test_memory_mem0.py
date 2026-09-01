"""Tests for the mem0 facts backend client (`_mem0`).

There is no mem0 instance in tests, so the httpx transport is faked and what is
under test is the orchestration: the scope namespace that isolates one
(org, agent, partition) from every other, the key riding in the header rather
than the URL, the liberal response parsing, and a network error becoming a
controlled refusal that carries no upstream text.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import ExternalServiceError
from app.services.memory import _mem0

pytestmark = pytest.mark.anyio

ORG, AGENT = uuid4(), uuid4()


class _Response:
    def __init__(self, *, data=None, error: Exception | None = None):
        self._data = data
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self):
        return self._data


class _Client:
    """A stand-in for httpx.AsyncClient that records the one request it is given."""

    def __init__(self, response: _Response):
        self._response = response
        self.calls: list[tuple[str, dict, dict]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, *, json: dict, headers: dict) -> _Response:
        self.calls.append((url, json, headers))
        return self._response


@pytest.fixture
def transport(monkeypatch):
    """Fake httpx.AsyncClient; the test sets `.response` and reads `.client.calls`."""
    holder = MagicMock()
    holder.response = _Response(data={})

    def _factory(**_kwargs):
        holder.client = _Client(holder.response)
        return holder.client

    monkeypatch.setattr(_mem0.httpx, "AsyncClient", _factory)
    return holder


def test_the_namespace_isolates_org_agent_and_partition():
    shared = _mem0._namespace(ORG, AGENT, None)
    per_user = _mem0._namespace(ORG, AGENT, "user:1")
    assert shared == f"{ORG}:{AGENT}:shared"
    assert per_user == f"{ORG}:{AGENT}:user:1"
    assert shared != per_user


class TestRemember:
    async def test_it_posts_the_fact_scoped_with_the_key_in_the_header(self, transport):
        await _mem0.mem0_remember(
            base_url=None,
            api_key="k-123",
            organization_id=ORG,
            agent_id=AGENT,
            scope_key="user:1",
            content="likes tea",
        )
        url, body, headers = transport.client.calls[0]
        assert url == "https://api.mem0.ai/v1/memories/"
        assert body["user_id"] == f"{ORG}:{AGENT}:user:1"
        assert body["messages"][0]["content"] == "likes tea"
        assert headers["Authorization"] == "Token k-123"

    async def test_a_self_hosted_base_url_is_used(self, transport):
        await _mem0.mem0_remember(
            base_url="https://mem0.internal/",
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            scope_key=None,
            content="x",
        )
        assert transport.client.calls[0][0] == "https://mem0.internal/v1/memories/"

    async def test_a_network_error_becomes_a_controlled_refusal(self, transport):
        transport.response = _Response(error=httpx.HTTPError("boom"))
        with pytest.raises(ExternalServiceError) as exc:
            await _mem0.mem0_remember(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                scope_key=None,
                content="x",
            )
        # The upstream text and the key never reach the refusal.
        assert "boom" not in str(exc.value.details)
        assert "k" not in str(exc.value.details)


class TestRecall:
    async def test_it_parses_a_results_envelope_into_hits(self, transport):
        transport.response = _Response(
            data={"results": [{"memory": "likes tea", "score": 0.9}, {"memory": "in Berlin"}]}
        )
        hits = await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            scope_key=None,
            query="q",
            limit=5,
        )
        assert [h.content for h in hits] == ["likes tea", "in Berlin"]
        assert hits[0].score == 0.9
        assert hits[1].score == 0.0

    async def test_it_parses_a_bare_list_and_alternate_text_keys(self, transport):
        transport.response = _Response(data=[{"text": "a"}, {"content": "b"}, {"nothing": "x"}])
        hits = await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            scope_key=None,
            query="q",
            limit=5,
        )
        assert [h.content for h in hits] == ["a", "b"]

    async def test_a_network_error_becomes_a_controlled_refusal(self, transport):
        transport.response = _Response(error=httpx.HTTPError("boom"))
        with pytest.raises(ExternalServiceError):
            await _mem0.mem0_recall(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                scope_key=None,
                query="q",
                limit=5,
            )
