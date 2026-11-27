"""Agent-memory repository (PostgreSQL async).

Every read is scoped to an agent and **one** owner, because a run touches exactly
one store - the conversation's own (`app.agents.memory_scope`). There is no union
to resolve, no precedence between stores and no name clash across them; a name is
unique within one owner's store and that is all it has to be.

That was not true while an organization-wide store existed alongside, and most of
what this module used to hold - an ordered read set, a `CASE` precedence, an
owner-kind filter for an operator listing - went with it (#1470).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.memory_keys import PERSON_PREFIX
from app.db.models.agent import Agent
from app.db.models.conversation import Conversation, Message
from app.db.models.memory import AgentMemoryFile, MemoryNoteRevision


def _last_written() -> Any:
    """When the agent last wrote this note, for ordering and for provenance.

    `written_at`, falling back to `created_at`, which is never null. Never
    `updated_at`: that advances on any write to the row, so a person suppressing
    a note would move it to the top of their own listing and make the page say
    the agent had written it at that moment (#1594 review).
    """
    return func.coalesce(AgentMemoryFile.written_at, AgentMemoryFile.created_at)


async def get_by_name(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    name: str,
    include_deactivated: bool = False,
    for_update: bool = False,
) -> AgentMemoryFile | None:
    """One note by name in one owner's store - every runtime lookup.

    `include_deactivated` is for the *write* path alone. A note the person
    suppressed is invisible to reading, editing and deleting, but the name is
    still taken in the database, so a create that could not see it would fail on
    the unique constraint with nothing useful to say (#1594).
    """
    query = select(AgentMemoryFile).where(
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.agent_id == agent_id,
        AgentMemoryFile.owner_key == owner_key,
        AgentMemoryFile.name == name,
    )
    if not include_deactivated:
        query = query.where(AgentMemoryFile.deactivated_at.is_(None))
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def list_for_owner(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    limit: int = 200,
    include_content: bool = True,
) -> list[AgentMemoryFile]:
    """One store's notes, newest first - the listing behind `list_memory`.

    Capped at `limit` and ordered newest-first so a long-lived store hands the
    model what it learned last rather than the alphabetically-first rows.
    `written_at` is the agent's own write and falls back to `created_at`, which is
    never null - deliberately not `updated_at`, which a person suppressing a note
    would move.
    """
    statement = (
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            AgentMemoryFile.owner_key == owner_key,
            # A suppressed note is not supplied to the model at all - which is
            # what "deactivated" has to mean to be worth offering (#1594).
            AgentMemoryFile.deactivated_at.is_(None),
        )
        .order_by(
            _last_written().desc(),
            AgentMemoryFile.name.asc(),
            # A stable final key, so a tie at the cap boundary is not resolved arbitrarily.
            AgentMemoryFile.id.asc(),
        )
        .limit(limit)
    )
    if not include_content:
        statement = statement.options(defer(AgentMemoryFile.content))
    result = await db.execute(statement)
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
    object_id: UUID | None = None,
    auto_update: bool = False,
    maintenance_source_at: datetime | None = None,
    maintenance_source_message_id: UUID | None = None,
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
        object_id=object_id,
        auto_update=auto_update,
        maintenance_source_at=maintenance_source_at,
        maintenance_source_message_id=maintenance_source_message_id,
        # The agent's own write, which is what provenance and ordering read.
        written_at=datetime.now(UTC),
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


async def replace_content(
    db: AsyncSession,
    *,
    file: AgentMemoryFile,
    content: str,
    changed_by: Literal["agent", "person", "maintenance", "restore"],
    source_message_id: UUID | None = None,
    source_at: datetime | None = None,
) -> AgentMemoryFile:
    """Replace a locked row and retain the previous body only when it changed."""
    if file.content == content:
        return file
    db.add(
        MemoryNoteRevision(
            organization_id=file.organization_id,
            note_id=file.id,
            content=file.content,
            changed_by=changed_by,
            source_message_id=source_message_id,
        )
    )
    values: dict[str, object] = {"content": content}
    if changed_by in {"agent", "maintenance"}:
        values["written_at"] = datetime.now(UTC)
    if source_at is not None:
        values["maintenance_source_at"] = source_at
        values["maintenance_source_message_id"] = source_message_id
    return await update(db, file=file, update_data=values)


async def note_revisions(
    db: AsyncSession, *, organization_id: UUID, note_id: UUID, skip: int, limit: int
) -> tuple[list[MemoryNoteRevision], int]:
    filters = (
        MemoryNoteRevision.organization_id == organization_id,
        MemoryNoteRevision.note_id == note_id,
    )
    rows = await db.scalars(
        select(MemoryNoteRevision)
        .where(*filters)
        .order_by(MemoryNoteRevision.replaced_at.desc(), MemoryNoteRevision.id.desc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count()).select_from(MemoryNoteRevision).where(*filters))
    return list(rows.all()), total or 0


async def note_revision_sources(
    db: AsyncSession, *, organization_id: UUID, owner_id: UUID, message_ids: Sequence[UUID]
) -> dict[UUID, UUID]:
    """Resolve source conversations still owned by the note's subject."""
    if not message_ids:
        return {}
    rows = await db.execute(
        select(Message.id, Conversation.id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Message.id.in_(message_ids),
            Conversation.organization_id == organization_id,
            Conversation.user_id == owner_id,
        )
    )
    return dict(rows.all())


async def note_revision(
    db: AsyncSession, *, organization_id: UUID, note_id: UUID, revision_id: UUID
) -> MemoryNoteRevision | None:
    return await db.scalar(
        select(MemoryNoteRevision).where(
            MemoryNoteRevision.organization_id == organization_id,
            MemoryNoteRevision.note_id == note_id,
            MemoryNoteRevision.id == revision_id,
        )
    )


async def search_notes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    terms: list[str],
    limit: int,
    object_id: UUID | None = None,
) -> list[AgentMemoryFile]:
    """Search the active note store before limiting, without loading note bodies."""
    if not terms and object_id is None:
        return []
    statement = select(AgentMemoryFile).where(
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.agent_id == agent_id,
        AgentMemoryFile.owner_key == owner_key,
        AgentMemoryFile.deactivated_at.is_(None),
    )
    if object_id is not None:
        statement = statement.where(AgentMemoryFile.object_id == object_id)
    if terms:
        search = func.to_tsquery("simple", " | ".join(terms))
        name = func.to_tsvector("simple", AgentMemoryFile.name)
        description = func.to_tsvector("simple", func.coalesce(AgentMemoryFile.description, ""))
        body = func.to_tsvector("simple", AgentMemoryFile.content)
        statement = statement.where(
            or_(
                name.bool_op("@@")(search),
                description.bool_op("@@")(search),
                body.bool_op("@@")(search),
            )
        ).order_by(
            (
                func.ts_rank(name, search) * 2
                + func.ts_rank(description, search)
                + func.ts_rank(body, search)
            ).desc()
        )
    rows = await db.scalars(
        statement.options(defer(AgentMemoryFile.content))
        .order_by(_last_written().desc(), AgentMemoryFile.id)
        .limit(limit)
    )
    return list(rows)


async def automatic_notes(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str,
    terms: list[str],
    max_chars: int,
    limit: int,
) -> list[AgentMemoryFile]:
    statement = select(AgentMemoryFile).where(
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.agent_id == agent_id,
        AgentMemoryFile.owner_key == owner_key,
        AgentMemoryFile.auto_update.is_(True),
        AgentMemoryFile.deactivated_at.is_(None),
        func.length(AgentMemoryFile.content) <= max_chars,
    )
    if terms:
        search = func.to_tsquery("simple", " | ".join(terms))
        name_rank = func.ts_rank(func.to_tsvector("simple", AgentMemoryFile.name), search)
        body_rank = func.ts_rank(func.to_tsvector("simple", AgentMemoryFile.content), search)
        statement = statement.order_by((name_rank + body_rank * 0.2).desc())
    rows = await db.scalars(
        statement.order_by(_last_written().desc(), AgentMemoryFile.id).limit(limit)
    )
    return list(rows.all())


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
    return result.rowcount or 0  # ty: ignore[missing-attribute]


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
    return result.rowcount or 0  # ty: ignore[missing-attribute]


async def list_for_person(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_key: str,
    skip: int = 0,
    limit: int = 50,
    q: str = "",
) -> tuple[list[AgentMemoryFile], int]:
    """One person's notes across every agent in the organization, and the total.

    Across agents, because the question somebody asks of their own memory is
    "what is written down about me here", and answering it agent by agent makes
    them hunt. Suppressed notes are included: they are the person's own, and a
    view that hid what they had suppressed would be a view they could not undo
    anything from (#1594).

    Newest first, on the same `written_at` the model's own listing uses, so the two
    agree about what "recent" means - and neither is moved by somebody suppressing
    a note, which `updated_at` would have been.
    """
    where = (
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.owner_key == owner_key,
        or_(
            AgentMemoryFile.name.icontains(q, autoescape=True),
            AgentMemoryFile.description.icontains(q, autoescape=True),
            AgentMemoryFile.content.icontains(q, autoescape=True),
            AgentMemoryFile.agent_id.in_(
                select(Agent.id).where(Agent.name.icontains(q, autoescape=True))
            ),
        )
        if q
        else true(),
    )
    total = await db.scalar(select(func.count()).select_from(AgentMemoryFile).where(*where))
    result = await db.execute(
        select(AgentMemoryFile)
        .where(*where)
        .order_by(_last_written().desc(), AgentMemoryFile.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all()), total or 0


async def get_owned(
    db: AsyncSession,
    *,
    organization_id: UUID,
    owner_key: str,
    file_id: UUID,
    for_update: bool = False,
) -> AgentMemoryFile | None:
    """One note by id, only if it belongs to this store.

    The owner is part of the lookup rather than checked afterwards: this is what
    somebody's own delete and deactivate resolve through, and a lookup by id alone
    with a check bolted on is the shape that eventually loses the check.
    """
    statement = select(AgentMemoryFile).where(
        AgentMemoryFile.id == file_id,
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.owner_key == owner_key,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def revive_if_suppressed(
    db: AsyncSession,
    *,
    file_id: UUID,
    content: str,
    description: str | None,
    kind: str,
    object_id: UUID | None = None,
) -> bool:
    """Revive the row only if it is still suppressed, preserving its earlier body."""
    file = await db.scalar(
        select(AgentMemoryFile)
        .where(AgentMemoryFile.id == file_id, AgentMemoryFile.deactivated_at.is_not(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if file is None:
        return False
    await replace_content(db, file=file, content=content, changed_by="agent")
    await update(
        db,
        file=file,
        update_data={
            "description": description,
            "object_id": object_id,
            "kind": kind,
            "deactivated_at": None,
            "written_at": datetime.now(UTC),
            "auto_update": False,
        },
    )
    return True
