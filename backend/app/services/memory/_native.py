"""The agent's runtime note store - a short-lived session per operation.

A run must not read or write memory on the session it runs on. Holding that
session across a model call is the idle-in-transaction the budget baseline opens
its own session to avoid (#12), and `autoflush` would turn a later read into a
flush of a half-written row. So each function here opens its own session with
`get_db_context` - the pattern `embeddings_for_collection` uses to reach the
database mid-run - does one operation, and lets the context manager commit and
close it. That is also why a note written in a run that later fails still
persists: the write committed on its own session the moment it was made, which is
what a memory is supposed to do.

Every function takes one `owner_key`, because a run touches exactly one store -
the conversation's own. Which one that is, is decided in
`app.agents.memory_scope` and never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.db.session import get_db_context
from app.repositories import memory_repo


@dataclass(frozen=True)
class MemoryFileIndexEntry:
    """One row of the runtime listing - enough to decide whether to read the body."""

    name: str
    description: str | None
    kind: str


async def list_files(
    *, organization_id: UUID, agent_id: UUID, owner_key: str
) -> list[MemoryFileIndexEntry]:
    """The store's notes, detached from the session."""
    async with get_db_context() as db:
        rows = await memory_repo.list_for_owner(
            db, organization_id=organization_id, agent_id=agent_id, owner_key=owner_key
        )
        return [
            MemoryFileIndexEntry(name=row.name, description=row.description, kind=row.kind)
            for row in rows
        ]


async def read_file(
    *, organization_id: UUID, agent_id: UUID, owner_key: str, name: str
) -> str | None:
    """One note's body by name, or None when the store holds no such name."""
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        return None if row is None else row.content


async def write_file(
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    name: str,
    content: str,
    description: str | None,
    kind: str,
) -> bool:
    """Create a new note. False when the name is already taken in that store.

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
            )
        except IntegrityError:
            # A concurrent write took the name between the check and this insert; the
            # unique index is the real guard, so report the name taken like a sequential
            # collision.
            await db.rollback()
            return False
        return True


async def edit_file(
    *, organization_id: UUID, agent_id: UUID, owner_key: str, name: str, content: str
) -> bool:
    """Replace an existing note's body. False when there is no such name."""
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        if row is None:
            return False
        await memory_repo.update(db, file=row, update_data={"content": content})
        return True


async def delete_file(*, organization_id: UUID, agent_id: UUID, owner_key: str, name: str) -> bool:
    """Remove a note. False when there is no such name."""
    async with get_db_context() as db:
        row = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
        )
        if row is None:
            return False
        await memory_repo.delete(db, row)
        return True
