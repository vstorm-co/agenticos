"""Where a browse reaches the web, as the organization set it (#2130).

Resolved by the runner, where the vault is, and handed to the capability as a
resource - the same road its step model takes. The credentials are `SecretStr`,
so a resource that reaches a log line shows them masked.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

BROWSER_ROUTE_RESOURCE = "browser_route"
"""The `resources` key the runner hands a `BrowserRoute` under."""


@dataclass(frozen=True, slots=True)
class BrowserRoute:
    """How one organization's browses run, when it is anything but the default."""

    proxy_server: str | None = None
    """`scheme://host:port` the browser context sends its traffic through."""

    proxy_username: str | None = None
    proxy_password: SecretStr | None = None

    remote_url: SecretStr | None = None
    """A hosted browser's CDP address, its key already in the query - so secret too."""

    timezone: str | None = None
    locale: str | None = None
