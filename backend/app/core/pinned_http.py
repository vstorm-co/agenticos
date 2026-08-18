"""An HTTP client that connects to the address it validated.

:func:`app.core.sanitize.validate_webhook_url` checks a name and hands back a
string, so the caller resolves that name a second time to connect and whoever
controls the name decides what it answers the second time. Where the URL was
typed by an operator that gap is narrow. Where it was chosen by the party being
checked it is not: MCP OAuth discovery names its own authorization server, token
endpoint, registration endpoint and every redirect after them, so connecting one
hostile server is enough to aim it (#860).

:class:`PinnedAsyncClient` closes it for that flow. Every request it sends -
first hop or redirect - is checked by :func:`app.core.sanitize.resolve_pinned_url`
and then dialled **at the address that check approved**, with the original host
in the `Host` header and in TLS SNI so certificate verification is unchanged.
There is no second resolution for anyone to race.

Two things this deliberately does not do. It does not follow redirects: the
caller walks them, so it can bound them and decide what a new origin means.
And it does not rewrite the request the caller holds - the address is
substituted inside the transport, on a copy, so `response.request.url` is still
the URL the flow believes it asked for. That matters more than it looks:
`httpx` resolves a relative `Location` against the request it sent, and against
the dialled URL a relative redirect would land on the pinned IP with the name
lost.

Pydantic AI's `_ssrf.safe_download` is the same idea for a different shape - it
is a GET-and-download helper with its own size limits and redirect policy, where
this flow POSTs form-encoded token grants through the MCP SDK's own request
builders.
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.sanitize import PinnedAddress, resolve_pinned_url

# Pinning makes the connection pool's key an address rather than a name, and
# `sni_hostname` is read when a connection is opened, never when one is reused
# (httpcore matches on scheme/host/port alone). Two names answering the same
# address would therefore share a connection whose certificate was verified for
# only the first of them - so this pool keeps nothing alive to be shared. The
# flow it serves makes a handful of requests to several hosts, which is the
# shape that loses least by it.
_NO_REUSE = httpx.Limits(max_keepalive_connections=0)


def _dial(request: httpx.Request, pinned: PinnedAddress) -> httpx.Request:
    """Copy *request* addressed at the validated IP rather than the hostname."""
    headers = httpx.Headers(request.headers)
    headers["Host"] = request.url.netloc.decode("ascii")
    extensions = dict(request.extensions)
    if request.url.scheme == "https":
        extensions["sni_hostname"] = pinned.hostname
    return httpx.Request(
        request.method,
        request.url.copy_with(host=pinned.ip, port=pinned.port),
        headers=headers,
        stream=request.stream,
        extensions=extensions,
    )


class PinnedTransport(httpx.AsyncBaseTransport):
    """Validates each request's URL and sends it to the address that passed."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Raises `SSRFBlockedError` (a `ValueError`) rather than connecting."""
        pinned = await asyncio.to_thread(resolve_pinned_url, str(request.url))
        return await self._inner.handle_async_request(_dial(request, pinned))

    async def aclose(self) -> None:
        await self._inner.aclose()


class PinnedAsyncClient(httpx.AsyncClient):
    """An `httpx.AsyncClient` whose every hop is SSRF-checked and pinned.

    Redirects are off: a flow that lets a remote server choose its next address
    should count the hops and see each one, and the transport only ever sees a
    single request.

    `transport` replaces the network for a test; it is wrapped, not bypassed, so
    a test observes exactly what would go on the wire.
    """

    def __init__(
        self,
        *,
        timeout: httpx.Timeout,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            timeout=timeout,
            follow_redirects=False,
            transport=PinnedTransport(transport or httpx.AsyncHTTPTransport(limits=_NO_REUSE)),
        )
