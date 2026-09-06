"""Agent-memory repository (PostgreSQL async).

Every read is scoped to an agent and **one** owner, because a run touches exactly
one store - the conversation's own (`app.agents.memory_scope`). There is no union
to resolve, no precedence between stores and no name clash across them; a name is
unique within one owner's store and that is all it has to be.

That was not true while an organization-wide store existed alongside, and most of
what this module used to hold - an ordered read set, a `CASE` precedence, an
owner-kind filter for an operator listing - went with it (#1470).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.memory_keys import PERSON_PREFIX
from app.db.models.memory import AgentMemoryFile


async def get_by_name(
    db: AsyncSession, *, organization_id: UUID, agent_id: UUID, owner_key: str, name: str
) -> AgentMemoryFile | None:
    """One note by name in one owner's store - every runtime lookup."""
    result = await db.execute(
        select(AgentMemoryFile).where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            AgentMemoryFile.owner_key == owner_key,
            AgentMemoryFile.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    limit: int = 200,
) -> list[AgentMemoryFile]:
    """One store's notes, newest first - the listing behind `list_memory`.

    Capped at `limit` and ordered newest-first so a long-lived store hands the
    model what it learned last rather than the alphabetically-first rows;
    `updated_at` is null until a row is edited, so it falls back to `created_at`,
    which never is.
    """
    result = await db.execute(
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            AgentMemoryFile.owner_key == owner_key,
        )
        .order_by(
            func.coalesce(AgentMemoryFile.updated_at, AgentMemoryFile.created_at).desc(),
            AgentMemoryFile.name.asc(),
            # A stable final key, so a tie at the cap boundary is not resolved arbitrarily.
            AgentMemoryFile.id.asc(),
        )
        .limit(limit)
    )
    return list(result.scalars().all())


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    name: str,
    description: str | None,
    content: str,
    content_format: str,
    kind: str,
) -> AgentMemoryFile:
    file = AgentMemoryFile(
        organization_id=organization_id,
        agent_id=agent_id,
        owner_key=owner_key,
        name=name,
        description=description,
        content=content,
        format=content_format,
        kind=kind,
    )
    db.add(file)
    await db.flush()
    await db.refresh(file)
    return file


async def update(
    db: AsyncSession, *, file: AgentMemoryFile, update_data: dict[str, Any]
) -> AgentMemoryFile:
    for field, value in update_data.items():
        setattr(file, field, value)
    db.add(file)
    await db.flush()
    await db.refresh(file)
    return file


async def delete(db: AsyncSession, file: AgentMemoryFile) -> None:
    await db.delete(file)
    await db.flush()


async def delete_all_for_agent(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """Delete every note one agent holds, in every store; returns the count.

    A set-based delete rather than a row-by-row loop: there are no ORM cascades on
    this table to miss.
    """
    result = await db.execute(
        sa_delete(AgentMemoryFile).where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
        )
    )
    await db.flush()
    # `execute` is typed to return `Result`, which has no `rowcount`; a DML
    # statement actually returns a `CursorResult`, which does (see `resource_grant`).
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]


async def delete_for_person(db: AsyncSession, *, organization_id: UUID, owner_key: str) -> int:
    """Delete one person's notes across **every** agent; returns the count.

    Scoped to the organization and to a `person:` key, never an agent: "forget
    everything you know about me" is a fact about a person, not about one agent
    they happened to talk to, and answering it one agent at a time is how a
    deletion request ends up half-done.

    The prefix is asserted rather than trusted. A `room:` key here would erase a
    channel a dozen colleagues write to, on the strength of one person asking to be
    forgotten - so it raises rather than deletes.
    """
    if not owner_key.startswith(PERSON_PREFIX):
        raise ValueError(f"not a person store: {owner_key!r}")
    result = await db.execute(
        sa_delete(AgentMemoryFile).where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.owner_key == owner_key,
        )
    )
    await db.flush()
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
