"""Input sanitization utilities.

URL validation to prevent SSRF attacks.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

WEBHOOK_ALLOWED_SCHEMES = frozenset({"http", "https"})

METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "metadata",
        "instance-data",
    }
)
"""Names that only ever mean a cloud instance-metadata service.

Blocked by name as well as by address because a name is what somebody types and
`169.254.169.254` is what it resolves to. Neither is ever a service anybody runs.
"""

METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("fd00:ec2::254"),
    }
)
"""Instance-metadata addresses outside link-local, which a link-local test misses.

Alibaba Cloud's sits in CGNAT and AWS's IPv6 one in a unique-local range, both of
which a deployment may otherwise use for its own services.
"""

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
    away, plus one exemption a caller names (`trusted_hosts`). This function has
    no exemption and must not get one: every `PinnedAsyncClient` request, and so
    every OAuth discovery hop, is checked here, and dials the `ips` it returns.

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
    by the party being refused (`.claude/rules/exceptions-security.md`) - which
    on the OAuth path is the ordinary case rather than the exotic one. They name
    no *caller* either: the same refusals are read by somebody who typed an MCP
    server URL, by somebody who typed a `cdp_url`, and by nobody at all when a
    discovery document named the address (#861).

    Args:
        url: The URL to validate.
        allowed_schemes: Allowed URL schemes. Defaults to {"http", "https"}.

    Returns:
        The hostname, port and validated addresses to connect to.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        UrlRefusedError: If the URL is malformed. Every refusal raised here is
            one of these two, so a caller may quote the message; a bare
            `ValueError` reaching a caller from this function is a bug rather
            than a refusal, and would be one written by the standard library
            about text the caller sent.
    """
    if allowed_schemes is None:
        allowed_schemes = WEBHOOK_ALLOWED_SCHEMES
    return _pinned(*_checked_target(url, allowed_schemes))


def _checked_target(url: str, allowed_schemes: frozenset[str]) -> tuple[str, int]:
    """The form half of the policy: scheme, hostname, no userinfo, a valid port.

    Returns:
        The hostname, as `urlparse` spells it, and the port to connect to.

    Raises:
        SSRFBlockedError: If the scheme is not allowed or the URL has userinfo.
        UrlRefusedError: If the URL cannot be parsed, or has no hostname or an
            invalid port.
    """
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
    try:
        hostname.encode("idna")
    except UnicodeError as err:
        # The resolver encodes the name with this codec, which refuses an empty
        # label ("a..b") or one over 63 characters with an error that subclasses
        # ValueError but not UrlRefusedError - so callers that quote refusals
        # answered a 500 with the codec's message (#2352). Checked with the form,
        # not in `_pinned`, so a host on `MCP_ALLOWED_HOSTS`, which skips the
        # address half, cannot save a URL nothing can resolve either.
        raise UrlRefusedError("The URL's host name is not valid") from err

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
        # Read before the IP-literal branch so an unrequestable port is refused
        # there too, and so that branch's `except ValueError` cannot swallow it.
        raise UrlRefusedError("The URL has an invalid port") from err
    return hostname, port


def _pinned(hostname: str, port: int) -> PinnedAddress:
    """The address half of the policy: an IP literal, or every DNS answer, must not be blocked.

    Raises:
        SSRFBlockedError: If the address is blocked, or the name does not resolve.
    """
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_ip_blocked(str(addr)):
            raise SSRFBlockedError(
                f"Blocked: {hostname!r} resolves to a private/internal "
                f"address. SSRF protection does not allow requests to internal networks."
            )
        return PinnedAddress(hostname=hostname, port=port, ips=(str(addr),))

    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as err:
        raise SSRFBlockedError(f"Blocked: unable to resolve hostname {hostname!r}") from err

    if not addr_infos:
        raise SSRFBlockedError(f"Blocked: hostname {hostname!r} did not resolve to any address")

    ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        if _is_ip_blocked(ip_str):
            raise SSRFBlockedError(
                f"Blocked: {hostname!r} resolves to private/internal "
                f"address {ip_str!r}. SSRF protection does not allow requests to "
                f"internal networks."
            )
        ips.append(ip_str)

    return PinnedAddress(hostname=hostname, port=port, ips=tuple(dict.fromkeys(ips)))


def validate_webhook_url(url: str, *, trusted_hosts: frozenset[str] = frozenset()) -> str:
    """Refuse a URL that points inside the deployment's network.

    :func:`resolve_pinned_url` with the answer discarded - same policy, same
    refusals, except for a host the caller names in `trusted_hosts` - for the
    callers that only want a yes or no.

    **This is not DNS-rebinding protection, and for these callers it cannot be.**
    The validated URL is returned as the string it came in as, so both of them
    resolve the hostname a second time when they connect: the MCP client through
    :func:`app.agents.mcp.validate_mcp_url`, where the connection happens however
    long after the server was saved. A name answering a public address here and a
    private one there passes this check and reaches the private address (#840).

    That is bearable *only* because the URL is typed by an operator, so
    rebinding needs the person typing it to be the attacker. Where the URL is
    chosen by someone else, this function is the wrong one: the OAuth flow's
    discovery documents name their own endpoints and go through
    :class:`app.core.pinned_http.PinnedAsyncClient`, which dials the address it
    checked (#860), and a URL a *model* picked belongs in Pydantic AI's
    `safe_download`.

    The MCP client is also the one caller that passes `trusted_hosts`: a
    connection's own address may name a host the operator listed in
    `MCP_ALLOWED_HOSTS`, and for that host there is no address check at all -
    the list is the operator vouching for whatever the name resolves to.

    Args:
        url: The webhook URL to validate; http or https.
        trusted_hosts: Hostnames or IP literals spelled exactly as
            `urlparse(url).hostname` spells them - lower case, an IPv6 address
            without brackets, a trailing dot kept. The caller normalizes them;
            nothing here folds case. A listed host passes the form checks and
            is then neither resolved nor range-checked.

    Returns:
        The validated URL string.

    Raises:
        SSRFBlockedError: If the URL is blocked by SSRF protection.
        UrlRefusedError: If the URL is malformed.

    Example:
        >>> validate_webhook_url("https://example.com/webhook")
        "https://example.com/webhook"
        >>> validate_webhook_url("http://169.254.169.254/latest/meta-data/")
        Raises SSRFBlockedError
    """
    hostname, port = _checked_target(url, WEBHOOK_ALLOWED_SCHEMES)
    if hostname not in trusted_hosts:
        _pinned(hostname, port)
    return url
