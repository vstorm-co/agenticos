"""Remote MCP must dial the address admitted at the actual connection boundary."""

import asyncio
import socket
import threading
from collections.abc import Iterator

import httpx2
import pytest
from httpcore2._backends.auto import AutoBackend
from mcp import ClientSession

from app.agents import mcp, mcp_http
from app.core.config import settings
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import PrivateAllowlist, SSRFBlockedError

pytestmark = [pytest.mark.anyio, pytest.mark.security]

PUBLIC = "93.184.216.34"
METADATA = "169.254.169.254"


@pytest.mark.parametrize("path", ["/mcp", "/sse"])
@pytest.mark.parametrize("rebind", [False, True])
async def test_the_actual_mcp_connection_cannot_resolve_a_checked_name_again(
    monkeypatch: pytest.MonkeyPatch, path: str, rebind: bool
) -> None:
    answer = PUBLIC
    dials: list[str] = []

    def resolve(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        assert host == "mcp.example.test"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (answer, port))]

    async def stop_before_network(
        _self: AutoBackend, host: str, port: int, **_kwargs: object
    ) -> None:
        del port
        dials.append(host)
        raise RuntimeError("synthetic wire stopped before any network access")

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", stop_before_network)
    url = f"https://mcp.example.test{path}"
    assert await mcp.validate_mcp_url(url) == url
    if rebind:
        answer = METADATA

    with pytest.raises((RuntimeError, ExceptionGroup, SSRFBlockedError)):
        async with (
            asyncio.timeout(3),
            mcp._mcp_transport(url, None, timeout=1) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

    assert dials == ([] if rebind else [PUBLIC])


def _on_wire(monkeypatch: pytest.MonkeyPatch, wire: httpx2.MockTransport) -> None:
    def client(
        *,
        timeout: httpx2.Timeout,
        private_allowlist: PrivateAllowlist,
        allowlist_origin: str | None = None,
    ) -> PinnedAsyncClient:
        return PinnedAsyncClient(
            timeout=timeout,
            transport=wire,
            private_allowlist=private_allowlist,
            allowlist_origin=allowlist_origin,
        )

    monkeypatch.setattr(mcp_http, "PinnedAsyncClient", client)


@pytest.mark.parametrize(
    ("listed", "addresses", "admitted"),
    [
        (["private.mcp.test"], ["10.1.2.3"], True),
        (["10.1.2.3/32"], ["10.1.2.3"], True),
        ([], ["10.1.2.3"], False),
        (["private.mcp.test"], [METADATA], False),
        (["private.mcp.test"], ["127.0.0.1"], False),
        ([], [PUBLIC, "10.1.2.3"], False),
        (["private.mcp.test"], [], False),
    ],
)
async def test_only_operator_exceptions_can_admit_a_private_mcp_connection(
    monkeypatch: pytest.MonkeyPatch, listed: list[str], addresses: list[str], admitted: bool
) -> None:
    sent: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", listed)
    monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", [])
    monkeypatch.setattr(
        "app.core.sanitize.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [(2, 1, 6, "", (address, port)) for address in addresses],
    )
    _on_wire(monkeypatch, httpx2.MockTransport(respond))
    url = "http://private.mcp.test/mcp"
    async with mcp_http.McpHttpClientFactory(url, 3)() as client:
        if admitted:
            assert (await client.get(url)).status_code == 200
        else:
            with pytest.raises(SSRFBlockedError):
                await client.get(url)

    assert [request.url.host for request in sent] == (addresses if admitted else [])


async def test_a_public_connection_cannot_gain_operator_exceptions_from_later_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = PUBLIC
    sent: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200)

    monkeypatch.setattr(settings, "MCP_ALLOWED_HOSTS", [])
    monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["10.1.2.3/32"])
    monkeypatch.setattr(
        "app.core.sanitize.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [(2, 1, 6, "", (answer, port))],
    )
    _on_wire(monkeypatch, httpx2.MockTransport(respond))
    url = "https://public.mcp.test/mcp"
    async with mcp_http.McpHttpClientFactory(url, 3)() as client:
        assert (await client.get(url)).status_code == 200
        answer = "10.1.2.3"
        with pytest.raises(SSRFBlockedError):
            await client.get("https://listed.mcp.test/message")

    assert len(sent) == 1 and sent[0].url.host == PUBLIC


async def test_factory_auth_and_headers_survive_without_replaying_an_uncertain_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx2.Request] = []

    class Auth(httpx2.Auth):
        def auth_flow(self, request: httpx2.Request) -> Iterator[httpx2.Request]:
            request.headers["X-Auth"] = "synthetic-proof"
            yield request

    def uncertain(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        raise httpx2.ReadError("the server may have accepted this write")

    monkeypatch.setattr(
        "app.core.sanitize.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [
            (2, 1, 6, "", (ip, port)) for ip in (PUBLIC, "93.184.216.35")
        ],
    )
    _on_wire(monkeypatch, httpx2.MockTransport(uncertain))
    url = "https://public.mcp.test/mcp"
    async with mcp_http.McpHttpClientFactory(url, 3)(
        headers={"X-Test": "sdk-header"}, auth=Auth(), follow_redirects=True
    ) as client:
        assert client.follow_redirects is False
        with pytest.raises(httpx2.ReadError):
            await client.post(url, json={"method": "tools/call"})

    assert len(sent) == 1
    assert sent[0].method == "POST"
    assert sent[0].headers["x-auth"] == "synthetic-proof"
    assert sent[0].headers["x-test"] == "sdk-header"


async def test_concurrent_mcp_requests_share_one_initial_exception_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    origins: list[str] = []

    def policy(url: str, listed: PrivateAllowlist) -> PrivateAllowlist:
        origins.append(url)
        entered.set()
        assert release.wait(3)
        return listed

    monkeypatch.setattr("app.core.pinned_http.allowlist_for", policy)
    monkeypatch.setattr(
        "app.core.sanitize.socket.getaddrinfo",
        lambda _host, port, **_kwargs: [(2, 1, 6, "", (PUBLIC, port))],
    )
    _on_wire(monkeypatch, httpx2.MockTransport(lambda _request: httpx2.Response(200)))
    url = "https://public.mcp.test/mcp"
    async with mcp_http.McpHttpClientFactory(url, 3)() as client:
        first = asyncio.create_task(client.get(url))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            second = asyncio.create_task(client.get(url))
            await asyncio.sleep(0)
        finally:
            release.set()
        results = await asyncio.gather(first, second)

    assert [result.status_code for result in results] == [200, 200]
    assert origins == [url]
