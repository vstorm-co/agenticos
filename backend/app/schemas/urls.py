"""Addresses of infrastructure an operator runs, as a request body may carry them.

The platform validates a URL in three different ways, on purpose, and which one
applies is decided by *whose* address it is:

* `app.core.sanitize.validate_webhook_url` - a callback somebody else handed us.
  A private address there is an SSRF attempt, so private, reserved, loopback and
  link-local are refused and the host must resolve to a public IP.
* `app.services.model_profile.validate_endpoint_url` - a model endpoint. Local
  models are first-class, so a private address is frequently the entire point.
* This module - a service the organization runs itself: a `sandboxd` host, a
  self-hosted Mattermost server. Same reasoning as a model endpoint, plus the
  two refusals that are never a legitimate service of either kind.

Kept here rather than in either caller's schema module because the second caller
arrived by needing exactly the first one's rule: a Mattermost server URL is
`https://mattermost.acme.internal` or `http://mattermost:8065` in compose, and a
private-range denylist would refuse the deployment the feature exists for.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated
from urllib.parse import urlparse

from pydantic import AfterValidator

_METADATA_HOSTS = frozenset(
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


def _service_address(value: str) -> str:
    """Refuse an address the platform must not be asked to fetch.

    This is not decoration. `SandboxConnectionService._get_json` performs a
    server-side GET against whatever is stored or probed here, with the
    connection's token attached, and hands the JSON body back to the caller; a
    Mattermost bot opens an authenticated WebSocket to its server and sends the
    bot token along. So an unvalidated string turns the API container into a
    fetch proxy for its own network, which is precisely the boundary `sandboxd`
    exists to draw. A holder of `connections:manage` or `channels:manage` is an
    organization operator, not the person who runs the deployment.

    What is refused, and why only this much:

    * **A scheme that is not http(s).** `httpx` has no transport for `file://` or
      `gopher://` so they fail anyway, but failing on a validator with a sentence
      beats failing on a stack trace.
    * **A missing host**, which is a typo rather than an attack, and would
      otherwise be fetched as a relative path against an empty base.
    * **Credentials in the URL.** Both callers authenticate with a vault-held
      token, so a `user:pass@` here is at best ignored and at worst the only
      copy of a password - and an address is named back in refusals, which puts
      it in the response and in the log line beside it (agenticos#342).
    * **Link-local addresses and the metadata hostnames**, because
      `169.254.169.254` and `metadata.google.internal` are never one of these
      services and are the one target where a single unauthenticated GET is
      worth something to an attacker.

    **RFC1918 is deliberately still allowed.** The legitimate address of a
    sandbox service *is* private - `http://sandboxd:8080` inside compose,
    `http://localhost:8080` for a developer running the API on their host - and
    so is a self-hosted Mattermost behind a VPN, which `docs/channels.md` gives
    as the example. A private-range denylist would refuse this project's own
    documented setup. That means this validator narrows the hole rather than
    closing it: a name that resolves to something internal still resolves, and
    DNS rebinding is not addressed here. The boundary that actually holds is the
    permission gate plus whatever egress policy the deployment puts around the
    API container; `docs/configuration.md` says so where it belongs.
    """
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("A service address must start with http:// or https://")
    host = parsed.hostname
    if not host:
        raise ValueError("A service address must name a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "A service address must not carry credentials in the URL - "
            "authentication is the key or token you pick for it"
        )
    if host.lower() in _METADATA_HOSTS:
        raise ValueError("That host is an instance-metadata service, not a service address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A name rather than a literal, which is the common case and cannot be
        # judged without resolving it - see the note about rebinding above.
        return value
    if address.is_link_local:
        raise ValueError("A link-local address is never a service address")
    return value


ServiceAddress = Annotated[str, AfterValidator(_service_address)]
"""An address this platform is willing to make a server-side request to.

One alias for every schema that carries one: a sandbox connection being created,
one being edited, one being probed before a row exists, and the server a
self-hosted channel bot belongs to. A copy per schema would be a copy per chance
for one of them - the probe takes an address straight from a request body - to be
the one that missed the rule.
"""
