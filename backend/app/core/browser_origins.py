"""Canonical browser credential destinations, before live DNS and page checks."""

import ipaddress
import re
from urllib.parse import urlsplit

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def browser_origin(value: str) -> str:
    """Accept an exact public HTTPS origin, never a URL pattern or credential URL.

    This validates syntax without DNS. The browser writer must also reject
    private DNS answers and recheck the live top-level and form destinations.
    Refusals never repeat submitted text, which may itself contain a password.
    """
    refused = "Use an exact public HTTPS origin without a path, credentials or wildcard"
    if not value or len(value) > 2048 or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError(refused)
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError(refused) from None
    if (
        parts.scheme != "https"
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.path not in ("", "/")
        or "?" in value
        or "#" in value
        or "\\" in value
        or port == 0
    ):
        raise ValueError(refused)
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError(refused) from None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        labels = host.split(".")
        if (
            len(labels) < 2
            or len(host) > 253
            or any(_HOST_LABEL.fullmatch(label) is None for label in labels)
            or all(label.isdecimal() for label in labels)
            or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise ValueError(refused) from None
    else:
        if not address.is_global:
            raise ValueError(refused)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"https://{host}" + (f":{port}" if port not in (None, 443) else "")
