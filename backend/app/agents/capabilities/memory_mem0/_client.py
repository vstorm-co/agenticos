"""The mem0 SDK, wrapped in the three guards it needs to be safe here.

`mem0ai`'s own client is what talks to mem0 - their API is theirs to change, and
a hand-rolled client pinned to `v1` is drift we would eat ourselves. What it is
not is safe to construct on an event loop, so this module is the adapter rather
than a re-export, and each guard below answers something checked against 2.0.20:

**The constructor makes a blocking network call.** `AsyncMemoryClient.__init__`
runs `_validate_api_key()`, which issues a synchronous `requests.get` against
`/v1/ping/` - on the loop, from the *async* client. So a client is built once per
credential in a worker thread (`asyncio.to_thread`) and cached, which turns an
unbounded per-call stall into a one-off cost off the loop. This is the same
discipline the file store applies to its own session (#12).

**Telemetry is opt-out and fires from that constructor.** `MEM0_TELEMETRY` is set
here, at import, rather than left to a default one missed environment variable
re-arms.

**The SDK does not vet a self-hosted host.** `mem0_base_url` comes from an agent
spec, so a builder who may bind (but not read) a shared key could otherwise point
it at their own server and capture the key from the `Authorization` header. A
self-hosted URL must be https and on `MEM0_ALLOWED_HOSTS`; an empty allowlist
refuses self-hosted mem0 outright, and the managed cloud needs no entry.

Isolation is the `user_id` namespace `{org}:{agent}:{owner}`, so one mem0 account
cannot mix two organizations', two agents', or two owners' memories. It is built
from the run's audience, never from the model.
"""

from __future__ import annotations

import asyncio
import logging
import os

# Before `mem0` is imported: the SDK reads this when its telemetry module loads,
# and its default is on.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from mem0 import AsyncMemoryClient

from app.core.config import settings
from app.core.exceptions import ExternalServiceError

__all__ = ["Mem0Fact", "mem0_forget_person", "mem0_recall", "mem0_remember", "namespace"]

logger = logging.getLogger(__name__)

_clients: dict[tuple[str, str | None], AsyncMemoryClient] = {}

# The SDK's constructor sets no timeout on its `/v1/ping/`, so an unreachable mem0
# would otherwise hold a run for as long as the socket does. Bounded here, since it
# is not bounded there.
_CONNECT_TIMEOUT = 15.0


class Mem0Fact:
    """One recalled memory and how close it was, detached from the client."""

    __slots__ = ("content", "score")

    def __init__(self, content: str, score: float) -> None:
        self.content = content
        self.score = score


def namespace(organization_id: UUID, agent_id: UUID, owner_key: str) -> str:
    """The mem0 `user_id` that isolates one (org, agent, owner) from every other.

    `owner_key` is required. There is no organization-wide fallback: a run with no
    store does not reach this function at all, and defaulting it to a shared bucket
    is how an anonymous visitor's memory would end up somewhere everybody reads.
    """
    return f"{organization_id}:{agent_id}:{owner_key}"


def _require_allowlisted_base_url(base_url: str | None) -> None:
    """Refuse to send the vault key to an unvetted self-hosted mem0 URL.

    The managed cloud (`base_url is None`) is trusted; a self-hosted URL must be
    https and its host on `MEM0_ALLOWED_HOSTS`, so an empty allowlist refuses
    self-hosted mem0 outright.

    The refusal names neither the URL nor a field. Not the URL, because a host -
    and anything in its query string - would reach a message that is logged (#342).
    Not a field, because `base_url` came from a stored spec rather than from
    anything this caller submitted, and `details={"field": ...}` is the singular
    shape #891 removed.
    """
    if base_url is None:
        return
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ExternalServiceError(
            message="A self-hosted mem0 URL must be https with a host",
            details={"operation": "connect"},
        )
    if parsed.hostname not in settings.MEM0_ALLOWED_HOSTS:
        raise ExternalServiceError(
            message="This deployment does not allow that self-hosted mem0 host",
            details={"operation": "connect"},
        )


async def _client(api_key: str, base_url: str | None) -> AsyncMemoryClient:
    """The client for one credential, built off the event loop and reused.

    Cached on `(api_key, base_url)` because the constructor's blocking ping is per
    credential, not per call.

    **Nothing is locked across the construction**, and that is deliberate rather
    than sloppy: the SDK's ping has no timeout of its own, so a process-wide lock
    held across it would turn one unreachable mem0 into every run in the process
    waiting on the same lock. Two cold callers may each build a client instead;
    `setdefault` then hands both the same one, and the loser is dropped. A rare
    duplicate ping is a much better trade than a wedge.

    `setdefault` needs no lock of its own - it is a single dict operation with no
    `await` inside it, so no other task can interleave.
    """
    _require_allowlisted_base_url(base_url)
    key = (api_key, base_url)
    cached = _clients.get(key)
    if cached is not None:
        return cached
    try:
        client = await asyncio.wait_for(
            asyncio.to_thread(_construct, api_key, base_url), _CONNECT_TIMEOUT
        )
    except TimeoutError as exc:
        # The thread outlives this, because a blocking socket read cannot be
        # cancelled - but the run is freed, which is the point.
        logger.warning("mem0_client_init_timed_out")
        raise ExternalServiceError(
            message="The mem0 memory service did not answer in time",
            details={"operation": "connect"},
        ) from exc
    return _clients.setdefault(key, client)


def _construct(api_key: str, base_url: str | None) -> AsyncMemoryClient:
    """Build the SDK client, translating its startup failure into a refusal.

    Runs in a worker thread, because `AsyncMemoryClient.__init__` validates the key
    with a synchronous `requests.get`. A bad key or an unreachable host therefore
    surfaces on the first tool call that needs a client, not at import - and it must
    not end the run: a memory service being down is a refusal the model reads, the
    same as any other external service.
    """
    try:
        return AsyncMemoryClient(api_key=api_key, host=base_url)
    except Exception as exc:
        # The SDK raises its own exception types and plain `ValueError`; the
        # upstream text goes to the log, never the refusal, because a client error
        # can echo the request and a URL carries a key in its query string (#342).
        logger.exception("mem0_client_init_failed")
        raise ExternalServiceError(
            message="Could not reach the mem0 memory service",
            details={"operation": "connect"},
        ) from exc


async def mem0_remember(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    content: str,
) -> None:
    """Store one memory in mem0, scoped to this (org, agent, owner)."""
    client = await _client(api_key, base_url)
    try:
        await client.add(
            [{"role": "user", "content": content}],
            user_id=namespace(organization_id, agent_id, owner_key),
        )
    except Exception as exc:
        logger.exception("mem0_remember_failed")
        raise ExternalServiceError(
            message="Could not save to the mem0 memory service",
            details={"operation": "remember"},
        ) from exc


async def _search_one(
    client: AsyncMemoryClient,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    query: str,
    limit: int,
) -> list[Mem0Fact]:
    """The memories most relevant to a query in one mem0 namespace."""
    try:
        data = await client.search(
            query,
            user_id=namespace(organization_id, agent_id, owner_key),
            limit=limit,
        )
    except Exception as exc:
        logger.exception("mem0_recall_failed")
        raise ExternalServiceError(
            message="Could not search the mem0 memory service",
            details={"operation": "recall"},
        ) from exc
    return _hits(data)


def _hits(data: Any) -> list[Mem0Fact]:
    """Read mem0's answer, which has had more than one shape.

    It has replied with both a bare list and a `{"results": [...]}` envelope, and
    names the text `memory`, `text` or `content`. Anything else is no hits rather
    than a crash: a memory search that cannot be parsed is a search that found
    nothing, not a failed run.
    """
    rows = data.get("results", []) if isinstance(data, dict) else data
    hits: list[Mem0Fact] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = row.get("memory") or row.get("text") or row.get("content")
        if text:
            score = row.get("score")
            hits.append(Mem0Fact(text, float(score) if isinstance(score, int | float) else 0.0))
    return hits


async def mem0_recall(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    query: str,
    limit: int,
) -> list[Mem0Fact]:
    """The memories most relevant to a query, in this conversation's own store."""
    client = await _client(api_key, base_url)
    return await _search_one(
        client,
        organization_id=organization_id,
        agent_id=agent_id,
        owner_key=owner_key,
        query=query,
        limit=limit,
    )


async def mem0_forget_person(
    *,
    base_url: str | None,
    api_key: str,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
) -> None:
    """Delete everything mem0 holds for one person, under one agent.

    The other half of "forget everything about me". These memories live outside
    this deployment, so the local delete cannot reach them - and a clear that
    reported success while mem0 still remembered would be a partial wipe wearing a
    success, which is the failure this whole feature is arranged against (#1470).

    Raises rather than swallowing: the caller has to be able to tell the person
    which half was done. A silent failure here is worse than an error, because the
    answer they get is "forgotten".
    """
    client = await _client(api_key, base_url)
    try:
        await client.delete_users(user_ids=[namespace(organization_id, agent_id, owner_key)])
    except Exception as exc:
        logger.exception("mem0_forget_failed")
        raise ExternalServiceError(
            message="Could not delete from the mem0 memory service",
            details={"operation": "forget"},
        ) from exc
