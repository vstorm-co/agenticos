"""Input sanitization utilities.

URL validation to prevent SSRF attacks.
"""

import ipaddress
import socket
from urllib.parse import urlparse

WEBHOOK_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Shared Address Space (RFC 6598) - CGNAT range.
# Python 3.11+ no longer classifies 100.64.0.0/10 as private or reserved,
# so we block it explicitly. Covers cloud metadata endpoints like
# Alibaba Cloud's 100.100.100.200.
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


class UrlRefusedError(ValueError):
    """A URL this deployment will not request, refused in a message we wrote.

    The type is the promise, and callers depend on it: both quote the message
    to a person - `mcp_connection._checked_url` as a 400, and
    `agent_registry._browser_use_problems` as a publish problem - and
    `.claude/rules/exceptions-security.md` allows that only for text written in
    this repository. `urlsplit` defers port parsing to attribute access and
    answers a bad one with `Port could not be cast to integer value as
    '<what you sent>'`, so a URL like `http://host:client_secret=sh-key/mcp`
    turns the stdlib's message into an echo of a secret (#861). Every refusal
    raised below is this type or a subclass, and `tests/test_ssrf.py` fails on
    one that is not.
    """


class SSRFBlockedError(UrlRefusedError):
    """Raised when a URL is blocked by SSRF protection.

    Dedicated exception type to avoid fragile string matching when
    distinguishing SSRF blocks from other refusals.
    """


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address is private, reserved, loopback, or link-local.

    Args:
        ip_str: The IP address string to check.

    Returns:
        True if the address should be blocked, False if it's safe.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        # If we can't parse it, block it to be safe
        return True

    return (
        addr.is_private
        or addr.is_reserved
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr in _CGNAT_NETWORK
    )


def validate_webhook_url(
    url: str,
    allowed_schemes: frozenset[str] | None = None,
) -> str:
    """Refuse a URL that points inside the deployment's network.

    Checks that the URL:
    - Uses an allowed scheme (http/https only by default)
    - Does not contain userinfo (credentials in the URL)
    - Does not point to private, reserved, loopback, or link-local IP addresses
    - Resolves, *at the moment of this call*, only to public addresses

    **This is not DNS-rebinding protection, and it cannot be.** The validated URL
    is returned as the string it came in as, so every caller resolves the
    hostname a second time when it connects - the MCP client through
    :func:`app.agents.mcp.validate_mcp_url`, and the browser through
    :func:`app.agents.capabilities.browser_use.validate_cdp_url`, where the
    attach happens however long after publish the agent is first run. A name
    answering a public address here and a private one there passes this check
    and reaches the private address. Closing that means pinning the resolved
    address into the request - dial the IP, send the original host in the `Host`
    header, the way `pydantic_ai._ssrf` does - and this function has no way to
    express that to its callers (#840).

    How much that gap costs depends on **who chose the URL**, and there are two
    answers, not one. Where it was typed by an operator - a connection's own
    URL, a `cdp_url` - rebinding needs the person typing it to be the attacker,
    which is narrow. But :func:`app.agents.mcp_oauth._send` validates every hop
    of an OAuth flow whose authorization server, token endpoint and redirects
    are all named by the *remote* MCP server's discovery documents. Connecting
    one hostile server is enough there; no operator has to be complicit, and
    that half is open until #860 pins the address. A URL that came from a
    *model*, or from anyone unprivileged, does not belong here at all - fetch it
    through Pydantic AI's `safe_download`, which pins the address it checked.

    Because of that, the refusals below name the **host**, or nothing, but never
    the URL. A URL carries a key in its query string, and the one being refused
    may have been written by the party being refused
    (`.claude/rules/exceptions-security.md`). They name no *caller* either: this
    function has had no webhook caller for some time, and every message it
    raises is read by somebody who typed an MCP server URL or a `cdp_url`
    (#861).

    Args:
        url: The URL to validate.
        allowed_schemes: Allowed URL schemes. Defaults to {"http", "https"}.

    Returns:
        The validated URL string.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        UrlRefusedError: If the URL is malformed. Every refusal raised here is
            one of these two, so a caller may quote the message; a bare
            `ValueError` reaching a caller from this function is a bug rather
            than a refusal, and would be one written by the standard library
            about text the caller sent.

    Example:
        >>> validate_webhook_url("https://example.com/webhook")
        "https://example.com/webhook"
        >>> validate_webhook_url("http://169.254.169.254/latest/meta-data/")
        Raises SSRFBlockedError
    """
    if allowed_schemes is None:
        allowed_schemes = WEBHOOK_ALLOWED_SCHEMES

    try:
        parsed = urlparse(url)
    except Exception as err:
        raise UrlRefusedError("The URL could not be parsed") from err

    if parsed.scheme not in allowed_schemes:
        raise SSRFBlockedError(
            f"URL scheme {parsed.scheme!r} is not allowed. "
            f"Allowed schemes: {', '.join(sorted(allowed_schemes))}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise UrlRefusedError("The URL has no hostname")

    # Reject URLs with userinfo (credentials) to prevent URL parsing ambiguities
    # e.g. http://user:pass@host/ or http://foo@169.254.169.254%00@public.com/
    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlockedError(
            "The URL must not contain credentials (userinfo). "
            "Remove the user:password@ portion from the URL."
        )

    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError as err:
        # `urlsplit` parses the port at attribute access rather than up front,
        # and says what it could not cast - which is the caller's text, and
        # reaches a response body through every caller of this function (#861).
        # Read here rather than beside `getaddrinfo` so an unrequestable port is
        # refused on an IP literal too, and so the `except ValueError` below
        # cannot swallow this.
        raise UrlRefusedError("The URL has an invalid port") from err

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(addr)):
            raise SSRFBlockedError(
                f"Blocked: {hostname!r} resolves to a private/internal "
                f"address. SSRF protection does not allow requests to internal networks."
            )
        return url
    except SSRFBlockedError:
        raise
    except ValueError:
        # Not an IP literal - continue to DNS resolution below
        pass

    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        raise SSRFBlockedError(f"Blocked: unable to resolve hostname {hostname!r}") from err

    if not addr_infos:
        raise SSRFBlockedError(f"Blocked: hostname {hostname!r} did not resolve to any address")

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        if _is_ip_blocked(ip_str):
            raise SSRFBlockedError(
                f"Blocked: {hostname!r} resolves to private/internal "
                f"address {ip_str!r}. SSRF protection does not allow requests to "
                f"internal networks."
            )

    return url
