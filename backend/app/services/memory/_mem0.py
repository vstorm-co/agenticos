"""A mem0 service as the facts backend, reached over its REST API.

httpx-direct rather than the `mem0ai` SDK. The SDK pulls `posthog` (phone-home
telemetry) and a `qdrant-client` this platform does not use - both at odds with
a self-hosted, privacy-conscious deployment - while `httpx` is already a
dependency, so this adds nothing and phones home nothing. The client is isolated
in this one module, so swapping to the SDK later is a single module's change.

The request and response shapes follow mem0's REST API and are the one part of
this the code cannot check locally: there is no mem0 instance in tests, so unit
tests mock the transport and a real mem0 (cloud or self-hosted, via
`mem0_base_url`) is the gate in CI/e2e.

Isolation: mem0's `user_id` is the whole scope namespace `{org}:{agent}:{key}`
(`shared` when there is no end-user), so one mem0 account cannot mix two
organizations', two agents', or two end-users' memories. The API key travels in
the `Authorization` header, never the URL, so an httpx error line cannot carry
it. The deployment's own metering does not see mem0's embedding cost - mem0
bills it, out of band (documented in docs/secrets.md).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.core.exceptions import ExternalServiceError
from app.repositories.memory import FactHit

logger = logging.getLogger(__name__)

_CLOUD_BASE_URL = "https://api.mem0.ai"
_TIMEOUT = 30.0


def _namespace(organization_id: UUID, agent_id: UUID, scope_key: str | None) -> str:
    """The mem0 `user_id` that isolates one (org, agent, partition) from every other."""
    return f"{organization_id}:{agent_id}:{scope_key or 'shared'}"


def _endpoint(base_url: str | None, path: str) -> str:
    return f"{(base_url or _CLOUD_BASE_URL).rstrip('/')}{path}"


async def mem0_remember(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    scope_key: str | None,
    content: str,
) -> None:
    """Store one fact in the mem0 service, scoped to this (org, agent, partition)."""
    payload: dict[str, Any] = {
        "messages": [{"role": "user", "content": content}],
        "user_id": _namespace(organization_id, agent_id, scope_key),
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _endpoint(base_url, "/v1/memories/"),
                json=payload,
                headers={"Authorization": f"Token {api_key}"},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        # The upstream text goes to the log, never the response: a client error
        # carries the request and could echo the payload, and the refusal only
        # needs to name what failed (agenticos#342).
        logger.exception("mem0_remember_failed")
        raise ExternalServiceError(
            message="Could not save to the mem0 memory service",
            details={"operation": "remember"},
        ) from exc


async def mem0_recall(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    scope_key: str | None,
    query: str,
    limit: int,
) -> list[FactHit]:
    """The facts most relevant to a query in the mem0 service, within the partition."""
    payload: dict[str, Any] = {
        "query": query,
        "user_id": _namespace(organization_id, agent_id, scope_key),
        "limit": limit,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                _endpoint(base_url, "/v1/memories/search/"),
                json=payload,
                headers={"Authorization": f"Token {api_key}"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        logger.exception("mem0_recall_failed")
        raise ExternalServiceError(
            message="Could not search the mem0 memory service",
            details={"operation": "recall"},
        ) from exc
    # mem0 has returned both a bare list and a `{"results": [...]}` envelope across
    # versions, and names the text `memory`, `text` or `content`; be liberal.
    rows = data.get("results", []) if isinstance(data, dict) else data
    hits: list[FactHit] = []
    for row in rows or []:
        text = row.get("memory") or row.get("text") or row.get("content")
        if text:
            hits.append(FactHit(content=text, score=float(row.get("score") or 0.0)))
    return hits
