"""Input sanitization utilities.

Webhook URL validation to prevent SSRF attacks.
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


class SSRFBlockedError(ValueError):
    """Raised when a URL is blocked by SSRF protection.

    Dedicated exception type to avoid fragile string matching when
    distinguishing SSRF blocks from other ValueErrors.
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

    Because of that, the refusals below name the **host** and never the URL. A
    URL carries a key in its query string, and the one this refuses may have
    been written by the party being refused (`.claude/rules/exceptions-security.md`).

    Args:
        url: The webhook URL to validate.
        allowed_schemes: Allowed URL schemes. Defaults to {"http", "https"}.

    Returns:
        The validated URL string.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        ValueError: If the URL is malformed.

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
        raise ValueError("Webhook URL could not be parsed") from err

    if parsed.scheme not in allowed_schemes:
        raise SSRFBlockedError(
            f"URL scheme {parsed.scheme!r} is not allowed. "
            f"Allowed schemes: {', '.join(sorted(allowed_schemes))}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname")

    # Reject URLs with userinfo (credentials) to prevent URL parsing ambiguities
    # e.g. http://user:pass@host/ or http://foo@169.254.169.254%00@public.com/
    if parsed.username is not None or parsed.password is not None:
        raise SSRFBlockedError(
            "Webhook URL must not contain credentials (userinfo). "
            "Remove the user:password@ portion from the URL."
        )

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(addr)):
            raise SSRFBlockedError(
                f"Webhook URL blocked: {hostname!r} resolves to a private/internal "
                f"address. SSRF protection does not allow requests to internal networks."
            )
        return url
    except SSRFBlockedError:
        raise
    except ValueError:
        # Not an IP literal - continue to DNS resolution below
        pass

    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port

    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        raise SSRFBlockedError(
            f"Webhook URL blocked: unable to resolve hostname {hostname!r}"
        ) from err

    if not addr_infos:
        raise SSRFBlockedError(
            f"Webhook URL blocked: hostname {hostname!r} did not resolve to any address"
        )

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        if _is_ip_blocked(ip_str):
            raise SSRFBlockedError(
                f"Webhook URL blocked: {hostname!r} resolves to private/internal "
                f"address {ip_str!r}. SSRF protection does not allow requests to "
                f"internal networks."
            )

    return url
