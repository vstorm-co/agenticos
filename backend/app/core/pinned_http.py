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
and then dialled **at an address that check approved**, with the original host
in the `Host` header and in TLS SNI so certificate verification is unchanged.
There is no second resolution for anyone to race.

Two things this deliberately does not do. It does not follow redirects: the
caller walks them, so it can bound them and decide what a new origin means.
And it does not rewrite the request the caller holds - the address is
substituted inside the transport, on a copy, so `response.request.url` is still
the URL the flow believes it asked for. That matters more than it looks:
`httpx` resolves a relative `Location` against the request it sent, and against
the dialled URL a relative redirect would land on the pinned IP with the name
lost. It is also why `NO_PROXY` and mount patterns still match on the host -
they are compared before the transport substitutes anything.

**A proxy resolves the destination itself, so on a proxied path the pin is a
request rather than a guarantee.** `HTTP_PROXY`/`HTTPS_PROXY` are honoured (a
deployment that mandates an egress proxy would otherwise lose MCP OAuth
entirely, and that proxy is its own egress control), and the pinned address is
what the proxy is asked to reach - `CONNECT 93.184.216.34:443`, or an
absolute-form request line for plain HTTP. What it does with that is the
proxy's business: a policy proxy may refuse a bare address, and a forwarding
proxy may prefer the `Host` header. TLS is still end to end, so a certificate
is still verified against the original name either way. The one line logged at
construction is so an operator reading a failure knows which path it took.

Pydantic AI's `_ssrf.safe_download` is the same idea for a different shape - it
is a GET-and-download helper with its own size limits and redirect policy, where
this flow POSTs form-encoded token grants through the MCP SDK's own request
builders.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.core.sanitize import PinnedAddress, resolve_pinned_url

logger = logging.getLogger(__name__)

# Pinning makes the connection pool's key an address rather than a name, and
# `sni_hostname` is read when a connection is opened, never when one is reused
# (httpcore matches on scheme/host/port alone). Two names answering the same
# address would therefore share a connection whose certificate was verified for
# only the first of them - so this pool keeps nothing alive to be shared. The
# flow it serves makes a handful of requests to several hosts, which is the
# shape that loses least by it.
_NO_REUSE = httpx.Limits(max_keepalive_connections=0)

# A failure to *connect* is the only one another address may be tried after:
# nothing was sent, so nothing is sent twice. A read or write failure means the
# token grant may already have been processed at the other end.
_UNREACHED = (httpx.ConnectError, httpx.ConnectTimeout)


def _dial(request: httpx.Request, pinned: PinnedAddress, ip: str, body: bytes) -> httpx.Request:
    """Copy *request* addressed at a validated IP rather than at the hostname.

    The body is passed as bytes rather than as the original stream so that a
    second address can be tried after a refused connection; a stream would be
    consumed by the first attempt.
    """
    headers = httpx.Headers(request.headers)
    headers["Host"] = request.url.netloc.decode("ascii")
    extensions = dict(request.extensions)
    if request.url.scheme == "https":
        extensions["sni_hostname"] = pinned.hostname
    return httpx.Request(
        request.method,
        request.url.copy_with(host=ip, port=pinned.port),
        headers=headers,
        content=body,
        extensions=extensions,
    )


class PinnedTransport(httpx.AsyncBaseTransport):
    """Validates each request's URL and sends it to an address that passed.

    Every address the name answered with was checked, so trying the next one
    after a refused connection widens nothing - it is what an ordinary client
    gets for free from the resolver, and without it a deployment that cannot
    reach the first record (an AAAA answer on an IPv4-only network) loses the
    whole flow.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Raises `SSRFBlockedError` (a `ValueError`) rather than connecting."""
        pinned = await asyncio.to_thread(resolve_pinned_url, str(request.url))
        body = await request.aread()
        *rest, final = pinned.ips
        for ip in rest:
            try:
                return await self._inner.handle_async_request(_dial(request, pinned, ip, body))
            except _UNREACHED as exc:
                logger.debug(
                    "Pinned address %s for %s is unreachable: %s", ip, pinned.hostname, exc
                )
        return await self._inner.handle_async_request(_dial(request, pinned, final, body))

    async def aclose(self) -> None:
        await self._inner.aclose()


class PinnedAsyncClient(httpx.AsyncClient):
    """An `httpx.AsyncClient` whose every hop is SSRF-checked and pinned.

    Redirects are off: a flow that lets a remote server choose its next address
    should count the hops and see each one, and the transport only ever sees a
    single request.

    `transport` replaces the network for a test; it is wrapped, not bypassed, so
    a test observes exactly what would go on the wire. Passing one also turns
    off `httpx`'s environment-proxy mounting, which is why the real client does
    not name a transport of its own.
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
            limits=_NO_REUSE,
            transport=transport,
        )
        # Read before written on purpose: `httpx` builds these in its own
        # `__init__` - the default pool, plus one mount per proxy the
        # environment names - and wrapping what it built is what applies the pin
        # to whichever of them a URL selects. Naming a transport here instead is
        # what silently turned those proxies off (#875).
        self._transport = PinnedTransport(self._transport)
        self._mounts = {
            pattern: None if mounted is None else PinnedTransport(mounted)
            for pattern, mounted in self._mounts.items()
        }
        if any(mounted is not None for mounted in self._mounts.values()):
            logger.info(
                "Outbound HTTP is proxied, so the validated address is what the proxy "
                "is asked to reach rather than what this process connects to."
            )
