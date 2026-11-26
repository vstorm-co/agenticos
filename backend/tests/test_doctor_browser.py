"""Browser diagnostics must send the IP Host header Chromium accepts."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from app.commands import doctor
from app.core.config import settings

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("address", ["172.18.0.4", "2001:db8::4"])
async def test_compose_browser_probe_uses_resolved_ip_and_reports_service_name(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser", "visual-render"])
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 9222))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    requests: list[httpx.Request] = []

    def chromium(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host != address:
            return httpx.Response(
                500, text="Host header is specified and is not an IP address or localhost."
            )
        return httpx.Response(200, json={"Browser": "Chrome/156"})

    client_type = httpx.AsyncClient

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(chromium))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert await doctor._browser_endpoints() == (
        "healthy",
        "browser (Chrome/156), visual-render (Chrome/156)",
    )
    assert len(requests) == 2
    assert all(
        request.url.path == "/json/version" and request.url.port == 9222 for request in requests
    )


@pytest.mark.parametrize("failure", ["dns", "empty", "http", "json", "timeout"])
async def test_unreachable_or_invalid_browser_remains_a_visible_diagnostic(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    lookup = AsyncMock(
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.4", 9222))]
    )
    if failure == "dns":
        lookup.side_effect = socket.gaierror("no such host")
    elif failure == "empty":
        lookup.return_value = []
    elif failure == "timeout":
        lookup.side_effect = TimeoutError
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)

    def chromium(_request: httpx.Request) -> httpx.Response:
        if failure == "http":
            return httpx.Response(500)
        return httpx.Response(200, text="not JSON")

    client_type = httpx.AsyncClient

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(chromium))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    status, detail = await doctor._browser_endpoints()
    assert status == "not_checked"
    assert "browser allowed, none answering on 9222" in detail


async def test_browser_resolution_does_not_swallow_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await doctor._browser_endpoints()


async def test_dns_resolution_shares_the_five_second_probe_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    original_timeout = asyncio.timeout
    deadlines: list[float] = []

    def timeout(delay: float) -> asyncio.Timeout:
        deadlines.append(delay)
        return original_timeout(0.001)

    async def stalled_lookup(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(60)

    monkeypatch.setattr(doctor.asyncio, "timeout", timeout)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", stalled_lookup)
    status, detail = await doctor._browser_endpoints()
    assert status == "not_checked"
    assert "none answering on 9222" in detail
    assert deadlines == [5.0]


@pytest.mark.parametrize("ipv4_responds", [True, False])
async def test_ipv4_browser_is_probed_after_an_unreachable_ipv6_address(
    monkeypatch: pytest.MonkeyPatch, ipv4_responds: bool
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["localhost"])
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 9222, 0, 0)),
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 9222, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9222)),
            ]
        ),
    )
    addresses: list[str] = []

    def chromium(request: httpx.Request) -> httpx.Response:
        addresses.append(request.url.host)
        if request.url.host == "::1" or not ipv4_responds:
            raise httpx.ConnectError("no listener", request=request)
        return httpx.Response(200, json={"Browser": "Chrome/156"})

    client_type = httpx.AsyncClient

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(chromium))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    status, detail = await doctor._browser_endpoints()
    assert addresses == ["::1", "127.0.0.1"]
    if ipv4_responds:
        assert (status, detail) == ("healthy", "localhost (Chrome/156)")
    else:
        assert status == "not_checked"
        assert "localhost allowed, none answering on 9222" in detail


async def test_address_fallbacks_share_one_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["localhost"])
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 9222, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 9222)),
            ]
        ),
    )
    original_timeout = asyncio.timeout
    deadlines: list[float] = []
    addresses: list[str] = []

    def timeout(delay: float) -> asyncio.Timeout:
        deadlines.append(delay)
        return original_timeout(0.01)

    async def chromium(request: httpx.Request) -> httpx.Response:
        addresses.append(request.url.host)
        if request.url.host == "::1":
            raise httpx.ConnectError("no listener", request=request)
        await asyncio.sleep(60)
        return httpx.Response(200, json={"Browser": "Chrome/156"})

    client_type = httpx.AsyncClient

    def client(*, timeout: float) -> httpx.AsyncClient:
        return client_type(timeout=timeout, transport=httpx.MockTransport(chromium))

    monkeypatch.setattr(doctor.asyncio, "timeout", timeout)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    status, detail = await doctor._browser_endpoints()
    assert status == "not_checked"
    assert "none answering on 9222" in detail
    assert addresses == ["::1", "127.0.0.1"]
    assert deadlines == [5.0]
