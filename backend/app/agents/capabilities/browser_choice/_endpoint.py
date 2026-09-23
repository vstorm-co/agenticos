"""Where the browser is, and where it is allowed to go.

Two decisions that are made about URLs rather than over the wire, so both are
pure and both are tested without a browser. They are also the two that are
security-relevant: one resolves an operator-supplied endpoint, the other is the
only thing standing between "browse the docs" and "browse the intranet".
"""

from __future__ import annotations

from fnmatch import fnmatch
from urllib.parse import urlparse, urlsplit

DEBUGGER_KEY = "webSocketDebuggerUrl"
"""The field `/json/version` answers with, and the one thing read out of it."""


class EndpointError(RuntimeError):
    """A CDP endpoint that cannot be used, said once and in the caller's words."""


def version_url(cdp_url: str) -> str:
    """The `/json/version` address for an HTTP CDP endpoint.

    Chromium publishes its WebSocket debugger address there, and the address
    carries a per-launch token, so it cannot be constructed - it has to be read.
    """
    return cdp_url.rstrip("/") + "/json/version"


def websocket_url(cdp_url: str, version: object) -> str:
    """The WebSocket to speak CDP over, addressed at the host the operator vetted.

    A `ws://` or `wss://` endpoint is already one and is returned unchanged; an
    `http(s)://` one is resolved through the `/json/version` payload passed in.

    **Only the path is taken from that payload.** The host and port come from the
    configured endpoint, and this is the whole point of the function rather than a
    detail. The payload is a response from something the agent's author named: a
    vetted endpoint that has been compromised, or one an author pointed at a
    server of their own, can answer with `ws://169.254.169.254/` or
    `ws://127.0.0.1:6379/` and have this deployment open a socket to it - an SSRF
    that arrives after every check has passed. The path is the only part that has
    to come from the browser, because it carries the per-launch token; the address
    is already known.

    It also happens to be what makes a proxied endpoint work at all: Chromium
    reports its own `127.0.0.1` in that field, so a browser reached through a
    sidecar or a port forward advertises an address that resolves to the caller.

    Args:
        cdp_url: What the agent's config holds, its host already on the
            operator's allowlist.
        version: The decoded `/json/version` body, or anything at all - a browser
            that answered with something else is a failure to report, not a shape
            to trust.

    Returns:
        A `ws://` or `wss://` URL at the configured host, with the browser's own path.

    Raises:
        EndpointError: The payload carried no usable debugger path.
    """
    if cdp_url.startswith(("ws://", "wss://")):
        return cdp_url
    configured = urlsplit(cdp_url)
    if isinstance(version, dict):
        found = version.get(DEBUGGER_KEY)
        if isinstance(found, str) and found.startswith(("ws://", "wss://")):
            advertised = urlsplit(found)
            scheme = "wss" if configured.scheme == "https" else "ws"
            path = advertised.path or "/"
            query = f"?{advertised.query}" if advertised.query else ""
            return f"{scheme}://{configured.netloc}{path}{query}"
    raise EndpointError(
        f"The CDP endpoint at {version_url(cdp_url)} did not answer with a "
        f"{DEBUGGER_KEY}. Check that it is a Chromium DevTools endpoint."
    )


BROWSABLE_SCHEMES = frozenset({"http", "https"})
"""What a browse may be pointed at, allowlist or no allowlist.

Checked before the host, and checked even when an agent has no `allowed_domains`
at all, because "anywhere" means anywhere *on the web*. `start_url` is written by
a model, and without this a generated `file:///etc/passwd` was navigated and its
contents read back through `read()` - the browser service's own filesystem
returned to the agent as the answer. `chrome://`, `view-source:` and `data:` are
the same shape of mistake.
"""


def domain_allowed(url: str, patterns: list[str] | None) -> bool:
    """Whether the agent may be on this URL.

    Two questions, and the scheme is the first. A URL that is not `http` or
    `https` is refused whatever the allowlist says - see
    :data:`BROWSABLE_SCHEMES`.

    Then the host. `None` means the agent was published without an allowlist and
    may go anywhere on the web. An empty list is *not* the same thing and does not
    mean that: an author who removed the last entry from an allowlist asked for
    nothing to be allowed, and reading it as "everything" is how a restriction
    becomes its opposite by deletion.

    Matching is on the host alone, case-folded, with `fnmatch` so `*.example.com`
    works. The port is deliberately not matched - a host is a trust boundary and a
    port is not - and a URL with no host at all is refused either way.
    """
    parsed = urlparse(url)
    if parsed.scheme not in BROWSABLE_SCHEMES:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if patterns is None:
        return True
    return any(fnmatch(host, pattern.lower()) for pattern in patterns)
