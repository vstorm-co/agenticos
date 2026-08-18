"""The client that dials what it validated (`app.core.pinned_http`).

The value here is a refusal and a substitution, so that is what these assert:
a name answering a private address never reaches the wire, and a name that
passes is connected to *at the address that passed* rather than resolved a
second time. `socket.getaddrinfo` is stubbed throughout - a test that reached
DNS would be testing the resolver's mood.
"""

import logging
from collections.abc import Callable, Iterator

import httpx
import pytest

from app.core.pinned_http import PinnedAsyncClient, PinnedTransport
from app.core.sanitize import SSRFBlockedError

pytestmark = pytest.mark.anyio

_PUBLIC = "93.184.216.34"
_SECOND_PUBLIC = "93.184.216.35"
_METADATA = "169.254.169.254"


class _Wire(httpx.AsyncBaseTransport):
    """The network, replaced: records what would actually have been sent."""

    def __init__(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        self._responder = responder
        self.sent: list[httpx.Request] = []
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.sent.append(request)
        return self._responder(request)

    async def aclose(self) -> None:
        self.closed = True


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="ok")


def _answers(monkeypatch: pytest.MonkeyPatch, *rounds: list[str]) -> list[str]:
    """Stub DNS with one answer per `getaddrinfo` call; record the names asked."""
    asked: list[str] = []
    remaining: Iterator[list[str]] = iter(rounds)

    def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple[object, ...]]:
        asked.append(host)
        ips = next(remaining, rounds[-1])
        return [(2, 1, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
    return asked


class TestTheValidatedAddressIsTheOneDialled:
    async def test_the_request_goes_to_the_ip_and_still_names_the_host(self, monkeypatch):
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            response = await client.get("https://mcp.example.com/.well-known/oauth")

        assert response.status_code == 200
        (sent,) = wire.sent
        assert sent.url.host == _PUBLIC
        assert sent.headers["Host"] == "mcp.example.com"
        assert sent.extensions["sni_hostname"] == "mcp.example.com"

    async def test_a_name_that_turns_private_after_the_check_is_never_re_resolved(
        self, monkeypatch
    ):
        """The whole point: rebinding needs a second resolution, and there is none.

        The stub answers public once and the metadata address for every call
        after it. A client that reconnected by name would reach 169.254.169.254.
        """
        asked = _answers(monkeypatch, [_PUBLIC], [_METADATA])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("https://rebind.example.com/token")

        assert asked == ["rebind.example.com"]
        (sent,) = wire.sent
        assert sent.url.host == _PUBLIC

    async def test_a_non_default_port_survives_into_the_host_header(self, monkeypatch):
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("https://mcp.example.com:8443/authorize")

        (sent,) = wire.sent
        assert (sent.url.host, sent.url.port) == (_PUBLIC, 8443)
        assert sent.headers["Host"] == "mcp.example.com:8443"

    async def test_plain_http_asks_for_no_sni(self, monkeypatch):
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("http://mcp.example.com/probe")

        (sent,) = wire.sent
        assert "sni_hostname" not in sent.extensions

    async def test_an_ipv6_answer_is_bracketed_when_dialled(self, monkeypatch):
        _answers(monkeypatch, ["2606:4700:4700::1111"])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("https://mcp.example.com/probe")

        (sent,) = wire.sent
        assert str(sent.url).startswith("https://[2606:4700:4700::1111]/")

    async def test_a_form_encoded_body_reaches_the_wire_unchanged(self, monkeypatch):
        """A token grant is a POST body, not a download - re-addressing must
        not lose it."""
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.post(
                "https://auth.example.com/token",
                data={"grant_type": "refresh_token", "refresh_token": "rt-1"},
            )

        (sent,) = wire.sent
        assert sent.method == "POST"
        assert sent.content == b"grant_type=refresh_token&refresh_token=rt-1"
        assert sent.headers["content-type"] == "application/x-www-form-urlencoded"


class TestARefusalReachesNoSocket:
    async def test_a_private_answer_is_refused_before_anything_is_sent(self, monkeypatch):
        _answers(monkeypatch, [_METADATA])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            with pytest.raises(SSRFBlockedError):
                await client.get("https://discovery.attacker.test/.well-known/oauth")

        assert wire.sent == []

    async def test_one_private_answer_among_public_ones_refuses_the_lot(self, monkeypatch):
        """Pinning the first address would otherwise make a mixed answer a race."""
        _answers(monkeypatch, [_PUBLIC, _METADATA])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            with pytest.raises(SSRFBlockedError):
                await client.get("https://mixed.attacker.test/token")

        assert wire.sent == []


class TestRedirectsKeepTheLogicalUrl:
    async def test_a_relative_location_resolves_against_the_name_not_the_address(self, monkeypatch):
        """`next_request` is built from the URL we asked for. Built from the
        dialled one instead, a relative redirect would lose the hostname and
        every hop after it would be addressed to a bare IP."""
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(lambda request: httpx.Response(302, headers={"Location": "/moved"}))

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            response = await client.get("https://mcp.example.com/start")

        assert response.next_request is not None
        assert str(response.next_request.url) == "https://mcp.example.com/moved"

    async def test_a_redirect_is_not_followed_by_the_client_itself(self, monkeypatch):
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(
            lambda request: httpx.Response(
                302, headers={"Location": f"https://{_SECOND_PUBLIC}/moved"}
            )
        )

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            response = await client.get("https://mcp.example.com/start")

        assert response.status_code == 302
        assert len(wire.sent) == 1


class TestEveryValidatedAddressIsUsable:
    """A name's other records are not thrown away: each one passed the same
    check, and an environment that cannot reach the first (an AAAA answer on an
    IPv4-only network) would otherwise lose the flow entirely.
    """

    async def test_the_next_validated_address_is_tried_when_a_connection_is_refused(
        self, monkeypatch
    ):
        _answers(monkeypatch, ["2606:4700:4700::1111", _PUBLIC])

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.host != _PUBLIC:
                raise httpx.ConnectError("network is unreachable", request=request)
            return httpx.Response(200, text="ok")

        wire = _Wire(responder)
        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            response = await client.get("https://mcp.example.com/probe")

        assert response.status_code == 200
        assert [r.url.host for r in wire.sent] == ["2606:4700:4700::1111", _PUBLIC]

    async def test_a_body_survives_being_tried_against_a_second_address(self, monkeypatch):
        """The first attempt must not consume the request stream - a token
        grant retried with an empty body is worse than a failed one."""
        _answers(monkeypatch, ["2606:4700:4700::1111", _PUBLIC])

        def responder(request: httpx.Request) -> httpx.Response:
            if request.url.host != _PUBLIC:
                raise httpx.ConnectError("network is unreachable", request=request)
            return httpx.Response(200, text="ok")

        wire = _Wire(responder)
        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.post("https://auth.example.com/token", data={"grant_type": "x"})

        assert [r.content for r in wire.sent] == [b"grant_type=x"] * 2

    async def test_a_failure_after_the_connection_is_not_retried(self, monkeypatch):
        """Only a refused connection proves nothing was sent. Anything later may
        have been acted on at the other end, so it is raised, not repeated."""
        _answers(monkeypatch, ["2606:4700:4700::1111", _PUBLIC])

        def responder(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadError("connection reset", request=request)

        wire = _Wire(responder)
        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            with pytest.raises(httpx.ReadError):
                await client.post("https://auth.example.com/token", data={"grant_type": "x"})

        assert len(wire.sent) == 1

    async def test_when_no_validated_address_answers_the_last_failure_is_raised(self, monkeypatch):
        _answers(monkeypatch, ["2606:4700:4700::1111", _PUBLIC])

        def responder(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout(f"timed out to {request.url.host}", request=request)

        wire = _Wire(responder)
        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            with pytest.raises(httpx.ConnectTimeout, match=_PUBLIC):
                await client.get("https://mcp.example.com/probe")

        assert len(wire.sent) == 2


class TestAConfiguredProxyIsStillUsed:
    """Naming a transport turns off `httpx`'s environment-proxy mounting, which
    would strand every deployment that requires an egress proxy. The mounts are
    read back through a private attribute because that is where `httpx` keeps
    the decision this class exists to preserve.
    """

    async def test_an_environment_proxy_is_mounted_and_pinned(self, monkeypatch, caplog):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")

        with caplog.at_level(logging.INFO, logger="app.core.pinned_http"):
            client = PinnedAsyncClient(timeout=httpx.Timeout(5.0))
        try:
            mounted = [t for t in client._mounts.values() if t is not None]
        finally:
            await client.aclose()

        assert mounted
        assert all(isinstance(transport, PinnedTransport) for transport in mounted)
        assert "proxied" in caplog.text

    async def test_nothing_is_said_about_a_proxy_when_there_is_none(self, monkeypatch, caplog):
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr("httpx._utils.getproxies", dict)

        with caplog.at_level(logging.INFO, logger="app.core.pinned_http"):
            client = PinnedAsyncClient(timeout=httpx.Timeout(5.0))
        await client.aclose()

        assert "proxied" not in caplog.text


class TestClosing:
    async def test_closing_the_client_closes_the_transport_it_wraps(self, monkeypatch):
        """The wrapper owns the pool; a no-op `aclose` would leak connections."""
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("https://mcp.example.com/probe")

        assert wire.closed is True
