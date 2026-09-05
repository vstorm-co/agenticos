"""Tests for the mem0 facts backend client (`_mem0`).

There is no mem0 instance in tests, so the httpx transport is faked and what is
under test is the orchestration: the scope namespace that isolates one
(org, agent, owner) from every other, the key riding in the header rather
than the URL, the liberal response parsing, and a network error becoming a
controlled refusal that carries no upstream text.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest

from app.core.exceptions import ExternalServiceError
from app.core.sanitize import UrlRefusedError
from app.services.memory import _mem0

pytestmark = pytest.mark.anyio

ORG, AGENT = uuid4(), uuid4()


class _Response:
    def __init__(
        self, *, data=None, error: Exception | None = None, json_error: Exception | None = None
    ):
        self._data = data
        self._error = error
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
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

    monkeypatch.setattr(_mem0, "PinnedAsyncClient", _factory)
    return holder


@pytest.fixture
def allow_self_hosted(monkeypatch):
    """Allowlist `mem0.internal`; SSRF/pinning is the pinned client's own concern."""
    monkeypatch.setattr(_mem0.settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])


def test_the_namespace_isolates_org_agent_and_owner():
    org = _mem0._namespace(ORG, AGENT, None)
    person = _mem0._namespace(ORG, AGENT, "person:1")
    room = _mem0._namespace(ORG, AGENT, "room:slack:C1")
    assert org == f"{ORG}:{AGENT}:org"
    assert person == f"{ORG}:{AGENT}:person:1"
    assert room == f"{ORG}:{AGENT}:room:slack:C1"
    assert len({org, person, room}) == 3


class TestRemember:
    async def test_it_posts_the_fact_scoped_with_the_key_in_the_header(self, transport):
        await _mem0.mem0_remember(
            base_url=None,
            api_key="k-123",
            organization_id=ORG,
            agent_id=AGENT,
            owner_key="person:1",
            content="likes tea",
        )
        url, body, headers = transport.client.calls[0]
        assert url == "https://api.mem0.ai/v1/memories/"
        assert body["user_id"] == f"{ORG}:{AGENT}:person:1"
        assert body["messages"][0]["content"] == "likes tea"
        assert headers["Authorization"] == "Token k-123"

    async def test_a_self_hosted_base_url_is_used(self, transport, allow_self_hosted):
        await _mem0.mem0_remember(
            base_url="https://mem0.internal/",
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            owner_key=None,
            content="x",
        )
        assert transport.client.calls[0][0] == "https://mem0.internal/v1/memories/"


class TestBaseUrlValidation:
    """The vault key never leaves for an unvetted URL: a self-hosted host
    must be https, allowlisted, and resolve to a public address."""

    async def _remember(self, base_url: str):
        await _mem0.mem0_remember(
            base_url=base_url,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            owner_key=None,
            content="x",
        )

    async def test_a_non_allowlisted_host_is_refused(self, monkeypatch):
        monkeypatch.setattr(_mem0.settings, "MEM0_ALLOWED_HOSTS", [])
        with pytest.raises(ExternalServiceError):
            await self._remember("https://evil.example.com/")

    async def test_a_non_https_url_is_refused(self, monkeypatch):
        monkeypatch.setattr(_mem0.settings, "MEM0_ALLOWED_HOSTS", ["mem0.internal"])
        with pytest.raises(ExternalServiceError):
            await self._remember("http://mem0.internal/")

    async def test_recall_validates_the_url_too(self, monkeypatch):
        monkeypatch.setattr(_mem0.settings, "MEM0_ALLOWED_HOSTS", [])
        with pytest.raises(ExternalServiceError):
            await _mem0.mem0_recall(
                base_url="https://evil.example.com/",
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                read_keys=(None,),
                query="q",
                limit=5,
            )

    async def test_a_network_error_becomes_a_controlled_refusal(self, transport):
        transport.response = _Response(error=httpx.HTTPError("boom"))
        with pytest.raises(ExternalServiceError) as exc:
            await _mem0.mem0_remember(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=None,
                content="x",
            )
        # The upstream text and the key never reach the refusal.
        assert "boom" not in str(exc.value.details)
        assert "k" not in str(exc.value.details)

    async def test_a_url_refused_on_the_wire_is_a_refusal_not_a_crashed_run(self, transport):
        """Not every refusal `resolve_pinned_url` raises is an SSRF one.

        The publish validator checks the scheme and the host but never the port, and
        the allowlist compares hostnames, so an allowlisted host with an unrequestable
        port reaches the wire and is refused there with a plain `UrlRefusedError`.
        Catching `SSRFBlockedError` alone let that escape the tool call and end the run.
        """
        transport.response = _Response(error=UrlRefusedError("The URL has an invalid port"))
        with pytest.raises(ExternalServiceError):
            await _mem0.mem0_remember(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                owner_key=None,
                content="x",
            )


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
            read_keys=(None,),
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
            read_keys=(None,),
            query="q",
            limit=5,
        )
        assert [h.content for h in hits] == ["a", "b"]

    async def test_no_person_searches_only_the_shared_namespace(self, transport):
        transport.response = _Response(data={"results": []})
        await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            read_keys=(None,),
            query="q",
            limit=5,
        )
        assert len(transport.client.calls) == 1
        assert transport.client.calls[0][1]["user_id"] == f"{ORG}:{AGENT}:org"

    async def test_it_unions_every_readable_store_merged_by_score_and_capped(self, monkeypatch):
        # Shared and personal namespaces are searched, merged by score and capped at
        # `limit`; the personal namespace is the run's own key, never another person's.
        responses = {
            f"{ORG}:{AGENT}:org": {
                "results": [{"memory": "s1", "score": 0.4}, {"memory": "s2", "score": 0.3}]
            },
            f"{ORG}:{AGENT}:person:1": {
                "results": [{"memory": "p1", "score": 0.95}, {"memory": "p2", "score": 0.35}]
            },
        }
        queried: list[str] = []

        class _MultiClient:
            async def __aenter__(self) -> "_MultiClient":
                return self

            async def __aexit__(self, *exc: object) -> bool:
                return False

            async def post(self, url: str, *, json: dict, headers: dict) -> _Response:
                queried.append(json["user_id"])
                return _Response(data=responses[json["user_id"]])

        monkeypatch.setattr(_mem0, "PinnedAsyncClient", lambda **_kwargs: _MultiClient())
        hits = await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            read_keys=("person:1", None),
            query="q",
            limit=3,
        )
        assert set(queried) == {f"{ORG}:{AGENT}:org", f"{ORG}:{AGENT}:person:1"}
        assert [h.content for h in hits] == ["p1", "s1", "p2"]

    async def test_a_network_error_becomes_a_controlled_refusal(self, transport):
        transport.response = _Response(error=httpx.HTTPError("boom"))
        with pytest.raises(ExternalServiceError):
            await _mem0.mem0_recall(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                read_keys=(None,),
                query="q",
                limit=5,
            )

    async def test_a_body_that_is_not_json_becomes_a_controlled_refusal(self, transport):
        # A 200 whose body is not JSON (an HTML error page) is a service failure, not a crash mid-run.
        transport.response = _Response(json_error=ValueError("no json here"))
        with pytest.raises(ExternalServiceError):
            await _mem0.mem0_recall(
                base_url=None,
                api_key="k",
                organization_id=ORG,
                agent_id=AGENT,
                read_keys=(None,),
                query="q",
                limit=5,
            )

    async def test_a_body_that_is_neither_list_nor_envelope_yields_no_hits(self, transport):
        transport.response = _Response(data="unexpected")
        hits = await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            read_keys=(None,),
            query="q",
            limit=5,
        )
        assert hits == []

    async def test_a_row_that_is_not_an_object_is_skipped(self, transport):
        transport.response = _Response(data={"results": ["not an object", {"memory": "kept"}]})
        hits = await _mem0.mem0_recall(
            base_url=None,
            api_key="k",
            organization_id=ORG,
            agent_id=AGENT,
            read_keys=(None,),
            query="q",
            limit=5,
        )
        assert [h.content for h in hits] == ["kept"]
