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
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import PERSON_PREFIX, is_person_key
from app.db.locks import LockScope, hold_subject
from app.db.models.user import User
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


async def _person_still_exists(db: AsyncSession, owner_key: str) -> bool:
    """Whether this note has somebody to be about, under the erasure's own lock.

    Only asked of a `person:` key; a room outlives every member of it. The lock
    is what makes the answer hold: `PersonalDataService.purge` takes the same one
    before it reads the table, so this either runs before the deletion - and the
    purge removes the note - or after it, and finds no row. Without it both
    transactions read a live account and the note survives the person (#1421).

    A key that is not a UUID is left alone rather than refused: the value space
    is `app.core.memory_keys`, and inventing a refusal here for a shape that
    module does not produce would be a second answer to the same question.
    """
    if not is_person_key(owner_key):
        return True
    try:
        user_id = UUID(owner_key.removeprefix(PERSON_PREFIX))
    except ValueError:
        return True
    await hold_subject(db, LockScope.PERSONAL_DATA_PER_USER, user_id)
    return await db.scalar(select(exists().where(User.id == user_id))) or False


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
        if not await _person_still_exists(db, owner_key):
            # Their account is being deleted, or is gone. `owner_key` has no
            # foreign key, so nothing else would have stopped this note from
            # being written about somebody who asked to be forgotten - and a
            # note that lands after the purge has read the table is personal
            # data the erasure reported as removed (#1421).
            return False
        # The write path is the one that sees a suppressed note, because the name
        # is taken in the database either way and a create that could not see it
        # would fail on the constraint with nothing useful to say. A suppressed
        # one is revived with the new content: what the person suppressed is
        # overwritten, and the row now holds something learned since (#1594).
        existing = await memory_repo.get_by_name(
            db,
            organization_id=organization_id,
            agent_id=agent_id,
            owner_key=owner_key,
            name=name,
            include_deactivated=True,
        )
        if existing is not None and existing.deactivated_at is None:
            return False
        if existing is not None:
            # Conditional, not a read then a write: two concurrent calls can both
            # see the row as suppressed, and Postgres would serialize the updates
            # while telling both they had won - losing the note the first wrote.
            # The loser is told the name is taken, which is this function's
            # answer for a live one.
            return await memory_repo.revive_if_suppressed(
                db,
                file_id=existing.id,
                content=content,
                description=description,
                kind=kind,
            )
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
        await memory_repo.update(
            db,
            file=row,
            # The agent's own write, which is what provenance and ordering read -
            # `updated_at` moves for a suppression too.
            update_data={"content": content, "written_at": datetime.now(UTC)},
        )
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
