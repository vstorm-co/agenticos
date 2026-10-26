"""Input sanitization utilities.

URL validation to prevent SSRF attacks.
"""

import ipaddress
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

import httpx2

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


_NAT64_PREFIX: Final = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(addr: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address *addr* carries - mapped, NAT64 well-known prefix or 6to4 - or None.

    A translator or relay turns these into a request to that IPv4 address, so a
    check that stops at the IPv6 spelling vets the wrong host. Other
    network-specific NAT64 prefixes cannot be told from an ordinary address.
    """
    if addr.ipv4_mapped:
        return addr.ipv4_mapped
    if addr in _NAT64_PREFIX:
        return ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
    return addr.sixtofour


def _is_never_reachable(ip_str: str) -> bool:
    """Whether an address stays refused even for a host the allowlist admits.

    The addresses the allowlist refuses as entries - loopback, link-local,
    unspecified and cloud metadata - plus multicast, which is never a server.
    Refused when a listed name *answers* one too, so a DNS record cannot open
    what the list itself may not name. An IPv6 address embedding one of them
    (IPv4-mapped, NAT64, 6to4) is refused as the address it embeds.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and (embedded := _embedded_ipv4(addr)):
        return _is_never_reachable_address(addr) or _is_never_reachable_address(embedded)
    return _is_never_reachable_address(addr)


def _is_never_reachable_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_multicast
        or addr in METADATA_ADDRESSES
    )


IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_NEVER_LISTED_NETWORKS: Final = tuple(
    ipaddress.ip_network(text)
    for text in (
        "127.0.0.0/8",
        "::1/128",
        "169.254.0.0/16",
        "fe80::/10",
        "0.0.0.0/32",
        "::/128",
        "224.0.0.0/4",
        "ff00::/8",
    )
)


def _embedded_forms(network: ipaddress.IPv4Network) -> tuple[ipaddress.IPv6Network, ...]:
    """The IPv6 networks whose addresses embed an address of *network* (NAT64 and 6to4)."""
    nat64 = ipaddress.IPv6Network(
        (int(_NAT64_PREFIX.network_address) | int(network.network_address), 96 + network.prefixlen)
    )
    sixtofour = ipaddress.IPv6Network(
        (0x2002 << 112 | int(network.network_address) << 80, 16 + network.prefixlen)
    )
    return nat64, sixtofour


_NEVER_LISTED_EMBEDDED: Final = tuple(
    form
    for never in (
        *_NEVER_LISTED_NETWORKS,
        *(
            ipaddress.IPv4Network(a)
            for a in METADATA_ADDRESSES
            if isinstance(a, ipaddress.IPv4Address)
        ),
    )
    if isinstance(never, ipaddress.IPv4Network)
    for form in _embedded_forms(never)
)
_LABEL: Final = re.compile(r"[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?")
_NUMERIC_IPV4_FORM: Final = re.compile(r"[0-9][0-9a-fx.]*")
_NEVER_REACHABLE_REASON: Final = (
    "a cloud metadata, link-local or loopback address or range. "
    "These stay refused whatever the list says, so remove it."
)


class PrivateAllowlistEntryError(ValueError):
    """An entry the allowlist refuses.

    `entry` is the text as configured, `reason` a sentence we wrote.
    """

    def __init__(self, entry: str, reason: str) -> None:
        super().__init__(f"{entry!r}, {reason}")
        self.entry = entry
        self.reason = reason


def wire_spelling(host: str) -> str:
    """*host* as httpx2 puts it in a request: a name IDNA-encoded, an address as written.

    httpx2's own encoder rather than the `idna` codec, which is IDNA 2003 and
    spells `straße` differently. A host it cannot encode is kept as typed and
    matches nothing it would send.
    """
    try:
        return httpx2.URL(scheme="http", host=host).raw_host.decode("ascii")
    except httpx2.InvalidURL:
        return host


def _unmapped(network: IpNetwork) -> IpNetwork:
    """An IPv4-mapped IPv6 network as the IPv4 network it names."""
    if isinstance(network, ipaddress.IPv6Network) and network.prefixlen >= 96:
        mapped = network.network_address.ipv4_mapped
        if mapped is not None:
            return ipaddress.IPv4Network((mapped, network.prefixlen - 96))
    return network


@dataclass(frozen=True)
class PrivateAllowlist:
    """The hosts and networks an operator vouched for, parsed once.

    `names` and `suffixes` hold each spelling a request may carry (the one
    `urlparse` reports and the IDNA one httpx2 sends), lower case. An empty list
    admits nothing, and is falsy.
    """

    names: frozenset[str] = frozenset()
    suffixes: tuple[str, ...] = ()
    networks: tuple[IpNetwork, ...] = ()
    entries: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.names or self.suffixes or self.networks)

    def admits_name(self, hostname: str) -> bool:
        """Whether *hostname* is listed exactly or under a listed suffix."""
        host = hostname.lower().removesuffix(".")
        return any(
            spelling in self.names or spelling.endswith(self.suffixes)
            for spelling in (host, wire_spelling(host))
        )

    def admits_address(self, hostname: str, ip: str) -> bool:
        """`admits_name(hostname)` or *ip* inside a network.

        Never an address `_is_never_reachable` names.
        """
        if _is_never_reachable(ip):
            return False
        if self.admits_name(hostname):
            return True
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in network for network in self.networks)


NO_PRIVATE_ADDRESSES: Final = PrivateAllowlist()


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
    *,
    private_allowlist: PrivateAllowlist = NO_PRIVATE_ADDRESSES,
) -> PinnedAddress:
    """Refuse a URL that points inside the deployment's network, and pin it.

    The policy is the whole of this module's SSRF policy - allowed scheme, no
    userinfo, and no private, reserved, loopback, link-local or CGNAT address -
    and :func:`validate_webhook_url` is this function with the answer thrown
    away. Every `PinnedAsyncClient` request, and so every OAuth discovery hop,
    is checked here, and dials the `ips` it returns.

    The one exemption is `private_allowlist`: a host it admits by name, or an
    answer inside one of its networks, may be private or CGNAT, but never an
    address :func:`_is_never_reachable` names. It is still resolved and pinned.
    A caller passes it only for a chain whose first URL needed it
    (:func:`allowlist_for`, the origin rule), so a redirect or a discovery
    document from a public host cannot aim a request at a listed one. The default
    admits nothing, so a caller that forgets it fails closed.

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
        private_allowlist: The operator's vouched hosts and networks, which may
            resolve inside the network. Empty by default.

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
    hostname, port = _checked_target(url, allowed_schemes)
    return _pinned(hostname, port, private_allowlist=private_allowlist)


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
        # not in `_pinned`, so a host admitted by name, which is accepted when it
        # does not resolve, cannot save a URL nothing can resolve either.
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


def _pinned(
    hostname: str,
    port: int,
    *,
    private_allowlist: PrivateAllowlist = NO_PRIVATE_ADDRESSES,
) -> PinnedAddress:
    """The address half of the policy: an IP literal, or every DNS answer, must not be blocked.

    With a `private_allowlist`, an address it admits for this host passes too,
    still never one :func:`_is_never_reachable` names.

    Raises:
        SSRFBlockedError: If the address is blocked, or the name does not resolve.
    """

    def blocked(ip: str) -> bool:
        return _is_never_reachable(ip) or (
            _is_ip_blocked(ip) and not private_allowlist.admits_address(hostname, ip)
        )

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if blocked(str(addr)):
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
        if blocked(ip_str):
            raise SSRFBlockedError(
                f"Blocked: {hostname!r} resolves to private/internal "
                f"address {ip_str!r}. SSRF protection does not allow requests to "
                f"internal networks."
            )
        ips.append(ip_str)

    return PinnedAddress(hostname=hostname, port=port, ips=tuple(dict.fromkeys(ips)))


def validate_webhook_url(
    url: str, *, private_allowlist: PrivateAllowlist = NO_PRIVATE_ADDRESSES
) -> str:
    """Refuse a URL that points inside the deployment's network.

    :func:`resolve_pinned_url` with the answer discarded - same policy, same
    refusals, except for what `private_allowlist` admits - for the callers that
    only want a yes or no.

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

    The MCP connection's own address is a caller that passes `private_allowlist`
    (`MCP_ALLOWED_HOSTS` and `OUTBOUND_PRIVATE_ALLOWLIST`). Every host is resolved
    and every answer checked: a loopback, link-local or metadata answer is refused
    whatever the list says, and a private one unless the list admits the host by
    name or the address by network. A host the list admits by name that does not
    resolve at all is accepted, so a compose service that is not up yet can be
    saved (#840).

    Args:
        url: The webhook URL to validate; http or https.
        private_allowlist: Hosts and networks the operator vouched for. Empty by
            default.

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
    try:
        _pinned(hostname, port, private_allowlist=private_allowlist)
    except SSRFBlockedError as err:
        if not (
            isinstance(err.__cause__, socket.gaierror) and private_allowlist.admits_name(hostname)
        ):
            raise
    return url


def _refuse_network(entry: str, network: IpNetwork) -> None:
    for never in (*_NEVER_LISTED_NETWORKS, *_NEVER_LISTED_EMBEDDED):
        if never.version == network.version and network.overlaps(never):
            raise PrivateAllowlistEntryError(entry, _NEVER_REACHABLE_REASON)
    if any(
        address in network for address in METADATA_ADDRESSES if address.version == network.version
    ):
        raise PrivateAllowlistEntryError(entry, _NEVER_REACHABLE_REASON)


def _address_of(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """*host* as an address the way the resolver reads it, or None for a name."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _NUMERIC_IPV4_FORM.fullmatch(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            return None
    return None


def _refuse_name(entry: str, host: str, *, suffix: bool) -> None:
    refused = {*METADATA_HOSTS, "localhost"}
    dotted = f".{host}"
    if host == "localhost" or host.endswith(".localhost"):
        raise PrivateAllowlistEntryError(entry, _NEVER_REACHABLE_REASON)
    if suffix:
        if any(name.endswith(dotted) for name in refused):
            raise PrivateAllowlistEntryError(
                entry, "a suffix that covers a cloud metadata or loopback name. Remove it."
            )
    elif host in refused:
        raise PrivateAllowlistEntryError(entry, _NEVER_REACHABLE_REASON)
    try:
        host.encode("idna")
    except UnicodeError as err:
        raise PrivateAllowlistEntryError(entry, "a host name that is not valid.") from err
    if not all(_LABEL.fullmatch(label) for label in wire_spelling(host).split(".")):
        raise PrivateAllowlistEntryError(
            entry, "not a host name, an address or a CIDR range. Write the host only."
        )


def parse_private_allowlist(entries: Iterable[str]) -> PrivateAllowlist:
    """Read configured entries into a :class:`PrivateAllowlist`.

    Each entry is an exact host (`wiki`), a suffix (`.corp.example`, which is not
    the apex), an IP literal (`10.0.0.5`, `[fd00::1]`) or a CIDR range. Blank
    entries are skipped.

    Raises:
        PrivateAllowlistEntryError: For an entry that is malformed or can reach
            loopback, link-local, multicast, unspecified or a metadata service.
    """
    names: set[str] = set()
    suffixes: list[str] = []
    networks: list[IpNetwork] = []
    kept: list[str] = []
    for entry in entries:
        text = entry.strip()
        if not text:
            continue
        host = text.removeprefix("[").removesuffix("]").lower().removesuffix(".")
        if "/" in host:
            try:
                network = ipaddress.ip_network(host, strict=False)
            except ValueError as err:
                raise PrivateAllowlistEntryError(
                    entry, "not a host name, an address or a CIDR range."
                ) from err
            network = _unmapped(network)
            _refuse_network(entry, network)
            networks.append(network)
        elif (address := _address_of(host)) is not None:
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            network = ipaddress.ip_network(address)
            _refuse_network(entry, network)
            networks.append(network)
        else:
            suffix = host.startswith(".")
            bare = host.removeprefix(".")
            if not bare:
                raise PrivateAllowlistEntryError(entry, "an empty suffix.")
            _refuse_name(entry, bare, suffix=suffix)
            spellings = {bare, wire_spelling(bare)}
            if suffix:
                suffixes.extend(sorted(f".{spelling}" for spelling in spellings))
            else:
                names.update(spellings)
        kept.append(text)
    return PrivateAllowlist(
        names=frozenset(names),
        suffixes=tuple(dict.fromkeys(suffixes)),
        networks=tuple(dict.fromkeys(networks)),
        entries=tuple(kept),
    )


def deployment_allowlist() -> PrivateAllowlist:
    """The operator's `OUTBOUND_PRIVATE_ALLOWLIST`, read on every call."""
    # Imported here: `app.core.config` imports this module for the parser.
    from app.core.config import settings

    return parse_private_allowlist(settings.OUTBOUND_PRIVATE_ALLOWLIST)


def mcp_allowlist() -> PrivateAllowlist:
    """The deployment list plus `MCP_ALLOWED_HOSTS`, which reaches MCP connections only."""
    from app.core.config import settings

    return parse_private_allowlist(
        [*settings.OUTBOUND_PRIVATE_ALLOWLIST, *settings.MCP_ALLOWED_HOSTS]
    )


def allowlist_for(url: str, listed: PrivateAllowlist | None = None) -> PrivateAllowlist:
    """The allowlist a request chain starting at *url* may use: the origin rule.

    A chain gets the list only when its first URL needs it - the host is listed by
    name, or it resolves only to public or admitted addresses with at least one
    admitted. A chain that starts public gets nothing, so a redirect or a
    discovery document cannot aim a request at a listed host. May resolve DNS:
    call it off the event loop.

    Args:
        url: The first URL of the chain, the one a member typed or bound.
        listed: The list to apply; the deployment's when omitted.
    """
    listed = deployment_allowlist() if listed is None else listed
    if not listed:
        return NO_PRIVATE_ADDRESSES
    try:
        hostname, port = _checked_target(url, WEBHOOK_ALLOWED_SCHEMES)
    except UrlRefusedError:
        return NO_PRIVATE_ADDRESSES
    if listed.admits_name(hostname):
        return listed
    try:
        _pinned(hostname, port)  # strict: a public origin earns nothing
    except SSRFBlockedError:
        pass
    else:
        return NO_PRIVATE_ADDRESSES
    try:
        _pinned(hostname, port, private_allowlist=listed)
    except SSRFBlockedError:
        return NO_PRIVATE_ADDRESSES
    return listed
