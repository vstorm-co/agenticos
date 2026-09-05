"""A mem0 service as the facts backend, reached over its REST API.

httpx-direct rather than the `mem0ai` SDK, and this is a decision, not an
oversight - the SDK (2.0.x) was re-evaluated and lost on five counts, recorded
here so the question is not re-opened. (1) It speaks mem0's *v3* API
(`/v3/memories/{add,search}/`), so it answers `404` against a self-hosted mem0
still on the `v1` this module targets. (2) Its client validates the key with a
blocking, synchronous request *in the constructor* - even `AsyncMemoryClient` -
which stalls the event loop this store opens its own session precisely to keep
free (#12), and costs a round trip per call unless the key is cached and held.
(3) It installs `posthog` and `qdrant-client` even with telemetry disabled -
weight this platform does not use. (4) That telemetry is opt-*out*
(`MEM0_TELEMETRY` defaults to `True`), a standing risk one missed env var
re-arms. (5) A test could only mock the SDK boundary, so it would assert our call
to the SDK, never the `user_id={org}:{agent}:{key}` namespace on the wire -
weakening the isolation guarantee below, which is the whole reason this backend
is careful. For this module's scope - one `add`, one `search` - the SDK buys
nothing, and `httpx` is already a dependency, so this adds nothing and phones home
nothing.

The trade is cheap to unwind: the client is isolated in this one module and the
config, secret and services are identical either way, so adopting the SDK later
is a single module's change. Revisit it for a reason the five counts do not
cover - mem0's graph memory or server-side filters, mem0 becoming the *primary*
memory store rather than an optional facts backend, or a self-hosted deployment
standardizing on `v3`.

The request and response shapes follow mem0's REST API and are the one part of
this the code cannot check locally: there is no mem0 instance in tests, so unit
tests mock the transport and a real mem0 (cloud or self-hosted, via
`mem0_base_url`) is the gate in CI/e2e.

Isolation: mem0's `user_id` is the whole scope namespace `{org}:{agent}:{key}`
(`shared` when there is no end-user), so one mem0 account cannot mix two
organizations', two agents', or two end-users' memories. The API key travels in
the `Authorization` header, never the URL, so an httpx error line cannot carry
it. A self-hosted `base_url` is refused unless it is https and on
`MEM0_ALLOWED_HOSTS`, and every request goes through `PinnedAsyncClient`, so the
key never reaches an unlisted origin or a host that resolves somewhere private.
The deployment's own metering does not see mem0's embedding cost - mem0
bills it, out of band (documented in docs/secrets.md).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.core.pinned_http import PinnedAsyncClient
from app.core.sanitize import UrlRefusedError
from app.repositories.memory import FactHit

logger = logging.getLogger(__name__)

_CLOUD_BASE_URL = "https://api.mem0.ai"
_TIMEOUT = 30.0


def _namespace(organization_id: UUID, agent_id: UUID, owner_key: str | None) -> str:
    """The mem0 `user_id` that isolates one (org, agent, owner) from every other."""
    return f"{organization_id}:{agent_id}:{owner_key or 'org'}"


def _endpoint(base_url: str | None, path: str) -> str:
    return f"{(base_url or _CLOUD_BASE_URL).rstrip('/')}{path}"


def _require_allowlisted_base_url(base_url: str | None) -> None:
    """Refuse to send the vault key to an unvetted self-hosted mem0 URL.

    `mem0_base_url` comes from the agent spec, so a builder who may bind (but not
    read) a shared key could otherwise point it at their own server and capture the
    key from the `Authorization` header. The managed cloud (`base_url is None`) is
    trusted; a self-hosted URL must be https and its host on `MEM0_ALLOWED_HOSTS`,
    so an empty allowlist refuses self-hosted mem0 outright. SSRF (a
    private/link-local/rebinding host) is handled separately, on the wire, by
    `PinnedAsyncClient`.
    """
    if base_url is None:
        return
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ExternalServiceError(
            message="A self-hosted mem0 URL must be https with a host",
            details={"operation": "mem0"},
        )
    if parsed.hostname not in settings.MEM0_ALLOWED_HOSTS:
        raise ExternalServiceError(
            message="This mem0 host is not on the deployment's allowlist",
            details={"operation": "mem0"},
        )


async def mem0_remember(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    content: str,
) -> None:
    """Store one fact in the mem0 service, scoped to this (org, agent, owner)."""
    _require_allowlisted_base_url(base_url)
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": content}],
        "user_id": _namespace(organization_id, agent_id, owner_key),
    }
    try:
        async with PinnedAsyncClient(timeout=httpx.Timeout(_TIMEOUT)) as client:
            response = await client.post(
                _endpoint(base_url, "/v1/memories/"),
                json=payload,
                headers={"Authorization": f"Token {api_key}"},
            )
            response.raise_for_status()
    except (httpx.HTTPError, UrlRefusedError) as exc:
        # `UrlRefusedError` is every refusal `resolve_pinned_url` raises, SSRF and
        # malformed alike: a URL the publish validator passed can still be refused on
        # the wire (an unrequestable port), and that is a refusal, not a crashed run.
        # The upstream text goes to the log, never the response: a client error can
        # echo the request payload, and the refusal only needs to name what failed (#342).
        logger.exception("mem0_remember_failed")
        raise ExternalServiceError(
            message="Could not save to the mem0 memory service",
            details={"operation": "remember"},
        ) from exc


async def _mem0_search_namespace(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    query: str,
    limit: int,
) -> list[FactHit]:
    """The facts most relevant to a query in one mem0 namespace."""
    _require_allowlisted_base_url(base_url)
    payload: dict[str, Any] = {
        "query": query,
        "user_id": _namespace(organization_id, agent_id, owner_key),
        "limit": limit,
    }
    try:
        async with PinnedAsyncClient(timeout=httpx.Timeout(_TIMEOUT)) as client:
            response = await client.post(
                _endpoint(base_url, "/v1/memories/search/"),
                json=payload,
                headers={"Authorization": f"Token {api_key}"},
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # `ValueError` covers a `JSONDecodeError` from a body that is not JSON - an
        # HTML error page answered 200, say - which is a service failure, not a crash.
        logger.exception("mem0_recall_failed")
        raise ExternalServiceError(
            message="Could not search the mem0 memory service",
            details={"operation": "recall"},
        ) from exc
    # mem0 has answered with both a bare list and a `{"results": [...]}` envelope, and
    # names the text `memory`, `text` or `content`; anything else is no hits, not a crash.
    rows = data.get("results", []) if isinstance(data, dict) else data
    hits: list[FactHit] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = row.get("memory") or row.get("text") or row.get("content")
        if text:
            score = row.get("score")
            hits.append(
                FactHit(content=text, score=float(score) if isinstance(score, int | float) else 0.0)
            )
    return hits


async def mem0_recall(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    query: str,
    limit: int,
) -> list[FactHit]:
    """The facts most relevant to a query, across every store the run reads.

    mem0 searches one namespace per call and a run reads up to three stores, so
    this fans out over `read_keys`, merges by score and caps at `limit`. The keys
    are server-derived, so a namespace is only ever one the run was admitted to.

    The searches are independent, so they go out together: run one after another,
    a slow mem0 costs this tool call a whole `_TIMEOUT` window per store instead
    of one for all of them.
    """
    pages = await asyncio.gather(
        *(
            _mem0_search_namespace(
                base_url=base_url,
                api_key=api_key,
                organization_id=organization_id,
                agent_id=agent_id,
                owner_key=owner_key,
                query=query,
                limit=limit,
            )
            for owner_key in read_keys
        )
    )
    hits = [hit for page in pages for hit in page]
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:limit]
