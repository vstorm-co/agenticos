"""Docling Serve: the client a document parse and a connection's Test talk through.

Docling Serve is a self-hosted document converter the organization runs and names as
a `document_parser` service connection. Everything it says is untrusted text that may
carry content from a document, so nothing from a response body, the address or the key
is put into a message, a log line or an audit entry here: a failure is reported by its
kind alone.
"""

import re
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

import httpx

PROBE_TIMEOUT_SECONDS = 10.0
"""How long each of the Test's two calls may take."""

_SAFE_VERSION = re.compile(r"^[0-9A-Za-z.+_-]{1,64}$")

API_KEY_HEADER = "X-Api-Key"
"""The header Docling Serve reads its key from."""


@dataclass(frozen=True)
class DoclingTarget:
    """Where a Docling Serve is and the key it takes, resolved for one use."""

    connection_id: UUID | None  # None only for the create-time Test
    base_url: str  # no trailing slash
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class DoclingProbe:
    """What a Test learned: whether the address is a Docling Serve that accepts the key."""

    outcome: Literal["ok", "key_refused", "key_required", "unreachable", "not_docling"]
    version: str | None


async def probe(target: DoclingTarget, *, client: httpx.AsyncClient | None = None) -> DoclingProbe:
    """Check that `target` is a Docling Serve and that it accepts the key.

    `GET /version` answers without a key and names the server. A key is then proven
    with a status poll for a task id that cannot exist: an accepted key gets a 404, a
    refused or missing one a 401, and nothing is submitted or stored.
    """
    if client is not None:
        return await _probe(target, client)
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=False) as owned:
        return await _probe(target, owned)


async def _probe(target: DoclingTarget, client: httpx.AsyncClient) -> DoclingProbe:
    try:
        response = await client.get(f"{target.base_url}/version", timeout=PROBE_TIMEOUT_SECONDS)
    except httpx.HTTPError:
        return DoclingProbe("unreachable", None)
    if response.status_code != 200:
        return DoclingProbe("unreachable", None)
    named = _version_of(response)
    if named is None:
        return DoclingProbe("not_docling", None)
    # Shown to the operator, so only a plain version string is passed on: the
    # server is untrusted and a body of its choosing must not be echoed.
    version = named if _SAFE_VERSION.fullmatch(named) else None

    headers = {API_KEY_HEADER: target.api_key} if target.api_key else {}
    try:
        poll = await client.get(
            f"{target.base_url}/v1/status/poll/{uuid4()}",
            headers=headers,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return DoclingProbe("unreachable", version)
    if poll.status_code == 404:
        return DoclingProbe("ok", version)
    if poll.status_code == 401:
        return DoclingProbe("key_refused" if target.api_key else "key_required", version)
    return DoclingProbe("unreachable", version)


def _version_of(response: httpx.Response) -> str | None:
    """The `docling-serve` version a `/version` body names, or None if it names none."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    version = body.get("docling-serve")
    return version if isinstance(version, str) else None
