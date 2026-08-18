"""The client that dials what it validated (`app.core.pinned_http`).

The value here is a refusal and a substitution, so that is what these assert:
a name answering a private address never reaches the wire, and a name that
passes is connected to *at the address that passed* rather than resolved a
second time. `socket.getaddrinfo` is stubbed throughout - a test that reached
DNS would be testing the resolver's mood.
"""

from collections.abc import Callable, Iterator

import httpx
import pytest

from app.core.pinned_http import PinnedAsyncClient
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


class TestClosing:
    async def test_closing_the_client_closes_the_transport_it_wraps(self, monkeypatch):
        """The wrapper owns the pool; a no-op `aclose` would leak connections."""
        _answers(monkeypatch, [_PUBLIC])
        wire = _Wire(_ok)

        async with PinnedAsyncClient(timeout=httpx.Timeout(5.0), transport=wire) as client:
            await client.get("https://mcp.example.com/probe")

        assert wire.closed is True
