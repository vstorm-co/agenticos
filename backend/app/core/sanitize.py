"""Input sanitization utilities.

Webhook URL validation to prevent SSRF attacks.
"""

import ipaddress
import socket
from dataclasses import dataclass
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


@dataclass(frozen=True)
class PinnedAddress:
    """The addresses a URL was checked at, so the same ones can be dialled.

    `hostname` is what the URL named and what a `Host` header and TLS SNI must
    still say; `ips` holds every address :func:`resolve_pinned_url` approved,
    deduplicated and in the order the resolver gave them, and is never empty.
    Handing both to a caller is the whole difference between checking a name
    and connecting to what was checked (#860).

    Every entry passed the same check, so a caller may try them in turn - what
    it may not do is resolve the name again.
    """

    hostname: str
    port: int
    ips: tuple[str, ...]


def resolve_pinned_url(
    url: str,
    allowed_schemes: frozenset[str] | None = None,
) -> PinnedAddress:
    """Refuse a URL that points inside the deployment's network, and pin it.

    The policy is the whole of this module's SSRF policy - allowed scheme, no
    userinfo, and no private, reserved, loopback, link-local or CGNAT address -
    and :func:`validate_webhook_url` is this function with the answer thrown
    away.

    **Only a caller that dials the returned `ip` is protected from DNS
    rebinding.** A caller that takes the hostname back and connects by name
    resolves it a second time, and a name that answers public here and private
    there reaches the private address. `app.core.pinned_http` is what turns this
    answer into a request: it dials the IP, sends `hostname` in the `Host`
    header and passes it as `sni_hostname` so TLS still verifies the
    certificate against the name.

    All resolved addresses are checked and all of them are pinned, so a name
    that answers with one public and one private address is refused outright
    rather than raced or narrowed to its public half.

    The refusals name the **host**, or nothing, but never the URL. A URL carries
    a key in its query string, and the one being refused may have been written
    by the party being refused (`.claude/rules/exceptions-security.md`).

    Args:
        url: The URL to validate.
        allowed_schemes: Allowed URL schemes. Defaults to {"http", "https"}.

    Returns:
        The hostname, port and validated addresses to connect to.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        ValueError: If the URL is malformed.
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

    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_ip_blocked(str(addr)):
            raise SSRFBlockedError(
                f"Webhook URL blocked: {hostname!r} resolves to a private/internal "
                f"address. SSRF protection does not allow requests to internal networks."
            )
        return PinnedAddress(hostname=hostname, port=port, ips=(str(addr),))

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

    ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        if _is_ip_blocked(ip_str):
            raise SSRFBlockedError(
                f"Webhook URL blocked: {hostname!r} resolves to private/internal "
                f"address {ip_str!r}. SSRF protection does not allow requests to "
                f"internal networks."
            )
        ips.append(ip_str)

    return PinnedAddress(hostname=hostname, port=port, ips=tuple(dict.fromkeys(ips)))


def validate_webhook_url(
    url: str,
    allowed_schemes: frozenset[str] | None = None,
) -> str:
    """Refuse a URL that points inside the deployment's network.

    :func:`resolve_pinned_url` with the answer discarded - same policy, same
    refusals, for the two callers that only want a yes or no.

    **This is not DNS-rebinding protection, and for these callers it cannot be.**
    The validated URL is returned as the string it came in as, so both of them
    resolve the hostname a second time when they connect: the MCP client through
    :func:`app.agents.mcp.validate_mcp_url`, and the browser through
    :func:`app.agents.capabilities.browser_use.validate_cdp_url`, where the
    attach happens however long after publish the agent is first run. A name
    answering a public address here and a private one there passes this check
    and reaches the private address (#840).

    That is bearable *only* because both URLs are typed by an operator, so
    rebinding needs the person typing it to be the attacker. Where the URL is
    chosen by someone else, this function is the wrong one: the OAuth flow's
    discovery documents name their own endpoints and go through
    :class:`app.core.pinned_http.PinnedAsyncClient`, which dials the address it
    checked (#860), and a URL a *model* picked belongs in Pydantic AI's
    `safe_download`.

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
    resolve_pinned_url(url, allowed_schemes)
    return url
