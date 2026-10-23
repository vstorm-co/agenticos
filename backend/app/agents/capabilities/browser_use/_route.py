"""Where one agent's browses reach the web: built in, through a proxy, or a hosted browser (#2130).

A deployment's own address is the one sites block first, and a headless browser
next to the API is the one they recognise. So an agent's browser binding can send
its browses through a proxy - a residential or regional address - or run them in
a hosted browser reached over CDP, with the credential in the vault behind the
binding's `secret_id` and the address checked the way every other address a
tenant types is.

**Addresses inside the deployment's network are refused** unless the operator
named the host in `BROWSER_CDP_ALLOWED_HOSTS`: the browser dials a proxy and the
API dials a hosted browser, so an address somebody with `edit` on an agent typed
must not reach the database or the cloud's metadata service. An address is
checked at publish and again when a browse starts - the second check is what
stops a name that has been pointed somewhere private since.
"""

from dataclasses import dataclass, replace
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from zoneinfo import available_timezones

import anyio
from pydantic import SecretStr

from app.core.config import settings
from app.core.sanitize import PinnedAddress, UrlRefusedError, resolve_pinned_url

Connection = Literal["built_in", "proxy", "hosted"]

PROXY_SCHEMES = frozenset({"http", "https", "socks5"})
HOSTED_SCHEMES = frozenset({"wss"})
"""A hosted browser is reached over TLS, where its key travels in the query."""
_VETTED_ONLY_SCHEMES = frozenset({"ws", "http", "https"})
"""Any other CDP address, allowed only at a host the operator named."""

AddressKind = Literal["proxy", "hosted"]


@dataclass(frozen=True, slots=True)
class BrowserRoute:
    """How one agent's browses run, when it is anything but the default."""

    proxy_server: str | None = None
    """`scheme://host:port` the browser context sends its traffic through."""

    proxy_username: str | None = None
    proxy_password: SecretStr | None = None

    remote_url: SecretStr | None = None
    """A hosted browser's CDP address, its key already in the query - so secret too."""

    remote_address: str | None = None
    """`remote_url` without the key, which is what gets checked and logged."""

    timezone: str | None = None
    locale: str | None = None


def _vetted(host: str) -> bool:
    """Whether the operator named this host as one a browser may be reached at."""
    return host.lower() in {name.strip().lower() for name in settings.BROWSER_CDP_ALLOWED_HOSTS}


def _schemes(kind: AddressKind, host: str | None) -> frozenset[str]:
    if kind == "proxy":
        return PROXY_SCHEMES
    return HOSTED_SCHEMES | (_VETTED_ONLY_SCHEMES if host and _vetted(host) else frozenset())


def address_problem(url: str, *, kind: AddressKind) -> str | None:
    """What is wrong with an address on its face, or `None`.

    No DNS: :func:`check_address` is this plus where the name points.
    """
    parts = urlsplit(url)
    schemes = _schemes(kind, parts.hostname)
    if parts.scheme not in schemes or not parts.hostname:
        return f"Use a {', '.join(sorted(schemes))} address with a host"
    if parts.username or parts.password:
        return "Keep the credentials out of the address; pick them from the vault"
    try:
        port = parts.port
    except ValueError:
        return "The port is not a number"
    if kind == "proxy" and port is None:
        return "A proxy address needs its port"
    return None


async def check_address(url: str, *, kind: AddressKind) -> PinnedAddress | None:
    """Refuse an address that is malformed or points inside the deployment's network.

    Returns the addresses it was checked at, or `None` for a host the operator
    vetted, which is not resolved here.

    Raises:
        UrlRefusedError: With the reason in a sentence that names no URL - a
            hosted browser's address may carry its key.
    """
    problem = address_problem(url, kind=kind)
    if problem is not None:
        raise UrlRefusedError(problem)
    parts = urlsplit(url)
    if _vetted(parts.hostname or ""):
        return None
    # Resolved off the event loop: it blocks on DNS. The scheme is the address's
    # own, because the check is about where it points rather than what it speaks.
    return await anyio.to_thread.run_sync(
        lambda: resolve_pinned_url(url, allowed_schemes=frozenset({parts.scheme}))
    )


async def recheck(route: BrowserRoute) -> BrowserRoute:
    """Check the route's addresses again as a browse starts, and pin its proxy.

    The proxy is handed to the browser at the address it was checked at, not by
    name: the browser would resolve the name again, and one that answered a
    public address here could answer an internal one there. An `https://` proxy
    keeps its name, which its certificate is issued for.

    Raises:
        UrlRefusedError: A name that pointed outside at publish points inside now.
    """
    if route.remote_address is not None:
        await check_address(route.remote_address, kind="hosted")
    if route.proxy_server is None:
        return route
    pinned = await check_address(route.proxy_server, kind="proxy")
    parts = urlsplit(route.proxy_server)
    if pinned is None or parts.scheme == "https":
        return route
    ip = pinned.ips[0]
    host = f"[{ip}]" if ":" in ip else ip
    return replace(route, proxy_server=f"{parts.scheme}://{host}:{pinned.port}")


def timezone_problem(timezone: str | None) -> str | None:
    """`None` for no time zone or a real IANA one."""
    if timezone and timezone not in available_timezones():
        return f"'{timezone}' is not an IANA time zone, such as Europe/Warsaw"
    return None


def _with_key(url: str, key_param: str, key: str | None) -> str:
    """The hosted browser's address with its key in the query, where it reads it."""
    if key is None:
        return url
    parts = urlsplit(url)
    query = "&".join(q for q in (parts.query, urlencode({key_param: key}, quote_via=quote)) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def route_for(
    *,
    connection: Connection,
    proxy_url: str,
    hosted_url: str,
    hosted_key_param: str,
    timezone: str | None,
    locale: str | None,
    credential: str | None,
) -> BrowserRoute | None:
    """The route a binding's settings describe; `None` for the plain built-in browser.

    `credential` is the binding's vault entry: `username:password` for a proxy,
    the key for a hosted browser.
    """
    if connection == "proxy" and proxy_url:
        username, _, password = (credential or "").partition(":")
        return BrowserRoute(
            proxy_server=proxy_url,
            proxy_username=username or None,
            proxy_password=SecretStr(password) if password else None,
            timezone=timezone,
            locale=locale,
        )
    if connection == "hosted" and hosted_url:
        return BrowserRoute(
            remote_url=SecretStr(_with_key(hosted_url, hosted_key_param, credential)),
            remote_address=hosted_url,
            timezone=timezone,
            locale=locale,
        )
    if timezone or locale:
        return BrowserRoute(timezone=timezone, locale=locale)
    return None
