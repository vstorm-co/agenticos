"""Input sanitization utilities.

This module provides security-focused input sanitization functions:
- Filename sanitization to prevent path traversal and unsafe characters
- Webhook URL validation to prevent SSRF attacks
"""

import ipaddress
import os
import re
import socket
import unicodedata
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


def sanitize_filename(filename: str, allow_unicode: bool = False) -> str:
    """Sanitize a filename to prevent path traversal and unsafe characters.

    Args:
        filename: The filename to sanitize.
        allow_unicode: Whether to allow unicode characters.

    Returns:
        A safe filename string.

    Example:
        >>> sanitize_filename("../../../etc/passwd")
        "etc_passwd"
        >>> sanitize_filename("hello world.txt")
        "hello_world.txt"
    """
    if not filename:
        return ""

    if allow_unicode:
        filename = unicodedata.normalize("NFKC", filename)
    else:
        filename = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")

    filename = os.path.basename(filename)
    filename = filename.replace("\x00", "")

    filename = re.sub(r"[/\\:*?\"<>|]", "_", filename)
    filename = re.sub(r"[\s_]+", "_", filename)
    filename = filename.strip("._")

    if not filename:
        return "unnamed"

    return filename


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
    """Validate a webhook URL to prevent SSRF attacks.

    Checks that the URL:
    - Uses an allowed scheme (http/https only by default)
    - Does not contain userinfo (credentials in the URL)
    - Does not point to private, reserved, loopback, or link-local IP addresses
    - Resolves via DNS to a public IP (prevents DNS rebinding attacks)

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
        raise ValueError(f"Invalid webhook URL: {url!r}") from err

    if parsed.scheme not in allowed_schemes:
        raise SSRFBlockedError(
            f"URL scheme {parsed.scheme!r} is not allowed. "
            f"Allowed schemes: {', '.join(sorted(allowed_schemes))}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid webhook URL: no hostname found in {url!r}")

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

    # TODO: socket.getaddrinfo() is blocking I/O - in async code paths
    # (PostgreSQL, MongoDB) consider using loop.getaddrinfo() or run_in_executor.
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
