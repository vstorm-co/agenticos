"""The Docling Serve client: what a connection's Test reads off the server.

Values are the ones measured against Docling Serve v1.39.0 (`GET /version` answers
without a key; an unknown task id is a 404 once the key is accepted and a 401
before).
"""

import httpx
import pytest

from app.services.rag import docling
from app.services.rag.docling import DoclingTarget

pytestmark = pytest.mark.anyio

_BASE = "http://docling.internal:5001"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _target(api_key: str | None = None) -> DoclingTarget:
    return DoclingTarget(connection_id=None, base_url=_BASE, api_key=api_key)


def _server(*, poll_status: int, version: dict[str, str] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            assert "x-api-key" not in request.headers
            return httpx.Response(200, json=version or {"docling-serve": "1.39.0"})
        assert request.url.path.startswith("/v1/status/poll/")
        return httpx.Response(poll_status, json={})

    return httpx.MockTransport(handle)


async def test_probe_ok_reports_version() -> None:
    async with _client(_server(poll_status=404)) as client:
        result = await docling.probe(_target("k"), client=client)

    assert (result.outcome, result.version) == ("ok", "1.39.0")


async def test_probe_sends_the_key_as_x_api_key_on_the_poll() -> None:
    seen: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.39.0"})
        seen.append(request.headers.get("x-api-key"))
        return httpx.Response(404)

    async with _client(httpx.MockTransport(handle)) as client:
        await docling.probe(_target("secret-key"), client=client)

    assert seen == ["secret-key"]


@pytest.mark.security
async def test_probe_key_refused() -> None:
    async with _client(_server(poll_status=401)) as client:
        result = await docling.probe(_target("stale"), client=client)

    assert (result.outcome, result.version) == ("key_refused", "1.39.0")


@pytest.mark.security
async def test_probe_key_required_without_key() -> None:
    async with _client(_server(poll_status=401)) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "key_required"


@pytest.mark.parametrize(
    "failure", [httpx.ConnectError("boom"), httpx.ReadTimeout("slow")], ids=["connect", "timeout"]
)
async def test_probe_unreachable_on_connect_error(failure: Exception) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise failure

    async with _client(httpx.MockTransport(handle)) as client:
        result = await docling.probe(_target(), client=client)

    assert (result.outcome, result.version) == ("unreachable", None)


async def test_probe_unreachable_on_a_non_200_version() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(502))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "unreachable"


async def test_probe_unreachable_when_the_poll_fails() -> None:
    async with _client(_server(poll_status=500)) as client:
        result = await docling.probe(_target("k"), client=client)

    assert (result.outcome, result.version) == ("unreachable", "1.39.0")


async def test_probe_unreachable_when_the_poll_cannot_connect() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/version":
            return httpx.Response(200, json={"docling-serve": "1.39.0"})
        raise httpx.ConnectError("gone")

    async with _client(httpx.MockTransport(handle)) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "unreachable"


@pytest.mark.parametrize(
    "body", [{"version": "1"}, ["docling-serve"], {"docling-serve": 3}], ids=str
)
async def test_probe_not_docling_without_version_field(body: object) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert (result.outcome, result.version) == ("not_docling", None)


async def test_probe_not_docling_on_a_body_that_is_not_json() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
    async with _client(transport) as client:
        result = await docling.probe(_target(), client=client)

    assert result.outcome == "not_docling"


async def test_probe_builds_its_own_client_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = httpx.AsyncClient
    transport = _server(poll_status=404)
    monkeypatch.setattr(
        docling.httpx, "AsyncClient", lambda **kwargs: real(transport=transport, **kwargs)
    )

    result = await docling.probe(_target("k"))

    assert result.outcome == "ok"


def test_the_target_hides_its_key_from_repr() -> None:
    assert "secret-key" not in repr(_target("secret-key"))


@pytest.mark.parametrize("version", ["x" * 65, "1.0 <script>", "", "1.39.0\n"], ids=str)
async def test_probe_does_not_echo_an_odd_version(version: str) -> None:
    async with _client(_server(poll_status=404, version={"docling-serve": version})) as client:
        result = await docling.probe(_target("k"), client=client)

    assert result.version is None
