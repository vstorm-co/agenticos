"""The agent's runtime memory store - a short-lived session per operation.

A run must not read or write memory on the session it runs on. Holding that
session across a model call is the idle-in-transaction the budget baseline opens
its own session to avoid (#12), and `autoflush` would turn a later read into a
flush of a half-written row. So each function here opens its own session with
`get_db_context` - the pattern `embeddings_for_collection` uses to reach the
database mid-run - does one operation, and lets the context manager commit and
close it. That is also why a memory written in a run that later fails still
persists: the write committed on its own session the moment it was made, which
is what a memory is supposed to do.

Reads take `read_keys` - the set of stores the run's audience admits, ordered
most-specific first, from `MemoryAudience.read_keys`. Writes take a single
resolved `owner_key`, chosen by the caller from the store the agent asked for,
never by the model naming one. Neither is ever derived here: this module is the
store, and who may reach it is decided in `app.agents.memory_scope`.

Every write here is `origin="agent"` - untrusted content a later run may read as
a tool result but that is never spliced into instructions unless the reader is
the only person it can influence (see `list_brief_facts` and the capability
README).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.memory_keys import MemoryOwnerKind, owner_kind
from app.db.models.memory import MemoryOrigin
from app.db.session import get_db_context
from app.repositories import memory_repo
from app.repositories.memory import FactHit
from app.services.rag.embeddings import EmbeddingService

_embedder: EmbeddingService | None = None


def _embedder_service() -> EmbeddingService:
    """The deployment embedder, built once and reused.

    Facts embed on the deployment `EMBEDDING_MODEL` (F-N2), so one instance
    serves every run; its client is lazy, so holding it costs no credential
    check until something actually embeds.
    """
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService(settings.rag)
    return _embedder


async def _embed(text: str) -> list[float]:
    """Embed off the event loop so a tool call does not block it for an HTTP
    round trip. `metered_by` copies into the thread, so the embedding is still
    booked to the run's ledger (N4)."""
    return await asyncio.to_thread(_embedder_service().embed_query, text)


async def embed_operator_fact(content: str) -> list[float]:
    """Embed an operator-seeded fact off the event loop.

    `embed_query` records its usage to whatever `metered_by` ledger is in context,
    and contextvars propagate into `asyncio.to_thread`, so the caller decides where
    the cost lands. The management facade wraps this in an org ledger it books to
    ingestion spend - the same as a RAG document, since a seed is off any run. The
    runtime `remember` embeds through `_embed`, whose own `metered_by` books it to
    the run instead.
    """
    return await asyncio.to_thread(_embedder_service().embed_query, content)


MutationResult = Literal["ok", "missing", "protected"]
"""The outcome of an agent's edit or delete.

`protected` is an agent reaching a row it may read but not change - an
operator-authored file. The agent can only ever *write* `agent` rows, so
`protected` is what stops it from mutating trusted, injectable content and
turning a poisoned edit into a prompt (the poisoning defense the capability
README describes).
"""


@dataclass(frozen=True)
class MemoryFileIndexEntry:
    """One row of the runtime index - enough to decide whether to read the body.

    `owner` is which store the row came from, so `list_memory` can label it and
    the agent can tell an organisation-wide note from this room's and from this
    person's - which is also what tells it which `scope` to edit the file in.
    """

    name: str
    description: str | None
    kind: str
    owner: MemoryOwnerKind


async def list_files(
    *, organization_id: UUID, agent_id: UUID, read_keys: Sequence[str | None]
) -> list[MemoryFileIndexEntry]:
    """The readable files, detached from the session.

    Each entry is tagged with the kind of store it came from, so the index can
    show whether a file is this person's, this room's or the organization's.
    """
    async with get_db_context() as db:
        rows = await memory_repo.list_readable(
            db, organization_id=organization_id, agent_id=agent_id, read_keys=read_keys
        )
        return [
            MemoryFileIndexEntry(
                name=row.name,
                description=row.description,
                kind=row.kind,
                owner=owner_kind(row.owner_key),
            )
            for row in rows
        ]


async def read_file(
    *, organization_id: UUID, agent_id: UUID, read_keys: Sequence[str | None], name: str
) -> str | None:
    """One readable file's body by name, or None when nothing readable matches.

    Searches every store the run reads; a name held in more than one resolves to
    the most specific, in `read_keys` order (see `get_readable_by_name`).
    """
    async with get_db_context() as db:
        row = await memory_repo.get_readable_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            read_keys=read_keys,
            name=name,
        )
        return None if row is None else row.content


async def write_file(
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    name: str,
    content: str,
    description: str | None,
    kind: str,
) -> bool:
    """Create a new file in the owner's store. False when the name is already taken.

    A collision is reported rather than silently overwritten: overwriting is
    `edit_file`, a deliberately separate act, so the model cannot lose a note by
    reaching for the wrong verb.
    """
    async with get_db_context() as db:
        existing = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        if existing is not None:
            return False
        try:
            await memory_repo.create(
                db,
                organization_id=organization_id,
                agent_id=agent_id,
                owner_key=owner_key,
                name=name,
                description=description,
                content=content,
                content_format="md",
                kind=kind,
                origin=MemoryOrigin.AGENT.value,
            )
        except IntegrityError:
            # A concurrent write took the name between the check and this insert; the
            # unique index is the real guard, so report the name taken like a sequential collision.
            await db.rollback()
            return False
        return True


async def edit_file(
    *, organization_id: UUID, agent_id: UUID, owner_key: str | None, name: str, content: str
) -> MutationResult:
    """Replace an existing agent-authored file's body.

    An operator-authored file in the same store is `protected`: the agent may
    read it but must not change it, or it could edit trusted, injectable content
    into a poisoned prompt. The origin of an edited row is left `agent`.
    """
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        if row is None:
            return "missing"
        if row.origin != MemoryOrigin.AGENT.value:
            return "protected"
        await memory_repo.update(db, file=row, update_data={"content": content})
        return "ok"


async def delete_file(
    *, organization_id: UUID, agent_id: UUID, owner_key: str | None, name: str
) -> MutationResult:
    """Remove an agent-authored file from the owner's store.

    An operator-authored file is `protected` for the same reason it is in
    `edit_file`: the agent may read the operator's standing memory but not delete
    it.
    """
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        if row is None:
            return "missing"
        if row.origin != MemoryOrigin.AGENT.value:
            return "protected"
        await memory_repo.delete(db, row)
        return "ok"


async def remember(
    *, organization_id: UUID, agent_id: UUID, owner_key: str | None, content: str
) -> None:
    """Embed a fact and store it in the owner's store.

    The embedding is computed before the session is opened - it is the slow part,
    and holding a session across it is the idle-in-transaction the file store
    avoids too. A fact written in a run that later fails still persists, the same
    as a file.
    """
    embedding = await _embed(content)
    async with get_db_context() as db:
        await memory_repo.create_fact(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            content=content,
            embedding=embedding,
            origin=MemoryOrigin.AGENT.value,
        )


async def recall(
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    query: str,
    limit: int = 5,
) -> list[FactHit]:
    """The facts most similar to a query, across every store the run reads."""
    embedding = await _embed(query)
    async with get_db_context() as db:
        return await memory_repo.recall_facts(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            read_keys=read_keys,
            query_embedding=embedding,
            limit=limit,
        )


async def memory_brief(
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    self_key: str | None,
    limit: int,
) -> list[str]:
    """The most recent facts safe to inject into the standing brief (see the repo).

    Non-semantic - no query, no embedding - because the brief is injected into the
    agent's instructions every request so it recalls without a tool call, and a
    query embedded there would spend off the run's ledger for nothing. Opens its own
    session, like `recall`, so a run never reads memory on the session it runs on.
    The trust filter (agent-authored content in a store somebody else also reads
    stays recall-only) lives in `list_brief_facts`; this only turns rows into lines.
    """
    async with get_db_context() as db:
        facts = await memory_repo.list_brief_facts(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            read_keys=read_keys,
            self_key=self_key,
            limit=limit,
        )
    return [fact.content for fact in facts]
