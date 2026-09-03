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

Reads union the shared store with the current person's, when the run has one:
`personal_key=None` is a run with no identified person and reads shared alone.
Writes take a single resolved `scope_key` - `None` for shared, a
`user:<id>`/`chan:<id>` for the person's own - chosen by the caller from the tier
the agent asked for, never by the model naming a partition. Every write here is
`origin="agent"` - untrusted content a later run may read as a tool result but
that is never spliced into instructions (see the capability README).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
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
    """Embed an operator-seeded fact off the event loop, unmetered.

    An operator seeding a fact is a management action, not an agent run, so there
    is no run ledger to book the embedding against (N4) - the deployment bears the
    cost, the way it does any other operator action. The runtime `remember` embeds
    through `_embed`, whose `metered_by` context books it to the run instead.
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

    `personal` is the tier the row came from - `True` for the current person's
    own store, `False` for the agent's shared store - so `list_memory` can label
    it and the agent can tell an organisation-wide note from this person's.
    """

    name: str
    description: str | None
    kind: str
    personal: bool


async def list_files(
    *, organization_id: UUID, agent_id: UUID, personal_key: str | None
) -> list[MemoryFileIndexEntry]:
    """The readable files - shared plus the current person's - detached from the session.

    Each entry is tagged with the tier it came from, so the index can show which
    store a file lives in. `personal_key=None` lists the shared store alone.
    """
    async with get_db_context() as db:
        rows = await memory_repo.list_readable(
            db, organization_id=organization_id, agent_id=agent_id, personal_key=personal_key
        )
        return [
            MemoryFileIndexEntry(
                name=row.name,
                description=row.description,
                kind=row.kind,
                personal=row.end_user_scope_key is not None,
            )
            for row in rows
        ]


async def read_file(
    *, organization_id: UUID, agent_id: UUID, personal_key: str | None, name: str
) -> str | None:
    """One readable file's body by name, or None when nothing readable matches.

    Searches the shared store and the current person's; a name in both tiers
    resolves to the person's own copy (see `get_readable_by_name`).
    """
    async with get_db_context() as db:
        row = await memory_repo.get_readable_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            personal_key=personal_key,
            name=name,
        )
        return None if row is None else row.content


async def write_file(
    *,
    organization_id: UUID,
    agent_id: UUID,
    scope_key: str | None,
    name: str,
    content: str,
    description: str | None,
    kind: str,
) -> bool:
    """Create a new file in the partition. False when the name is already taken.

    A collision is reported rather than silently overwritten: overwriting is
    `edit_file`, a deliberately separate act, so the model cannot lose a note by
    reaching for the wrong verb.
    """
    async with get_db_context() as db:
        existing = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            end_user_scope_key=scope_key,
            name=name,
        )
        if existing is not None:
            return False
        try:
            await memory_repo.create(
                db,
                organization_id=organization_id,
                agent_id=agent_id,
                end_user_scope_key=scope_key,
                name=name,
                description=description,
                content=content,
                content_format="md",
                kind=kind,
                origin=MemoryOrigin.AGENT.value,
            )
        except IntegrityError:
            # A concurrent write took the name between the check above and this
            # insert; the unique index is the real guard. Roll back the failed
            # flush and report the name taken, like a sequential collision, rather
            # than let the DataError-shaped crash end the run.
            await db.rollback()
            return False
        return True


async def edit_file(
    *, organization_id: UUID, agent_id: UUID, scope_key: str | None, name: str, content: str
) -> MutationResult:
    """Replace an existing agent-authored file's body.

    An operator-authored file in the same partition is `protected`: the agent may
    read it but must not change it, or it could edit trusted, injectable content
    into a poisoned prompt. The origin of an edited row is left `agent`.
    """
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            end_user_scope_key=scope_key,
            name=name,
        )
        if row is None:
            return "missing"
        if row.origin != MemoryOrigin.AGENT.value:
            return "protected"
        await memory_repo.update(db, file=row, update_data={"content": content})
        return "ok"


async def delete_file(
    *, organization_id: UUID, agent_id: UUID, scope_key: str | None, name: str
) -> MutationResult:
    """Remove an agent-authored file from the partition.

    An operator-authored file is `protected` for the same reason it is in
    `edit_file`: the agent may read the operator's standing memory but not delete
    it.
    """
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            end_user_scope_key=scope_key,
            name=name,
        )
        if row is None:
            return "missing"
        if row.origin != MemoryOrigin.AGENT.value:
            return "protected"
        await memory_repo.delete(db, row)
        return "ok"


async def remember(
    *, organization_id: UUID, agent_id: UUID, scope_key: str | None, content: str
) -> None:
    """Embed a fact and store it in the partition.

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
            end_user_scope_key=scope_key,
            content=content,
            embedding=embedding,
        )


async def recall(
    *, organization_id: UUID, agent_id: UUID, personal_key: str | None, query: str, limit: int = 5
) -> list[FactHit]:
    """The facts most similar to a query - shared plus the current person's - most-similar first."""
    embedding = await _embed(query)
    async with get_db_context() as db:
        return await memory_repo.recall_facts(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            personal_key=personal_key,
            query_embedding=embedding,
            limit=limit,
        )


async def memory_brief(
    *, organization_id: UUID, agent_id: UUID, personal_key: str | None, limit: int
) -> list[str]:
    """The most recent facts a run may read, for the standing memory brief.

    Non-semantic - no query, no embedding - because the brief is injected into the
    agent's instructions every request so it recalls without a tool call, and a
    query embedded there would spend off the run's ledger for nothing. Opens its own
    session, like `recall`, so a run never reads memory on the session it runs on.
    """
    async with get_db_context() as db:
        facts = await memory_repo.list_readable_facts(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            personal_key=personal_key,
            limit=limit,
        )
    return [fact.content for fact in facts]
