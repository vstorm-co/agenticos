"""Agent-memory repository (PostgreSQL async).

Every read is scoped to an agent and a set of owners. The owner key is nullable
and `NULL` means the organization's own store, so "belongs to this owner" is
`col IS NULL` for that case and `col = key` otherwise — a plain `col = NULL` is
never true and would make the organization store silently unreadable. The unique
index enforces the same rule at write time with `NULLS NOT DISTINCT`, so a read
and a uniqueness check agree on what "the same store" means.

Which owners a run may read is decided in `app.agents.memory_scope`, not here:
this module is handed the keys and trusts them, because they are derived from the
request's identity and never from the model. What it does own is the *ordering* of
that set — a name can exist in several stores, and the caller's precedence has to
survive into SQL (see `get_readable_by_name`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, case, func, or_, select, text
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.memory_keys import PERSON_PREFIX, ROOM_PREFIX, MemoryOwnerKind, OwnerFilter
from app.db.models.memory import AgentMemoryFact, AgentMemoryFile, MemoryOrigin
from app.repositories._search import contains_ci

MemorySort = Literal["name", "updated"]

# pgvector's HNSW index takes a `vector` column up to this width; past it the column
# is `halfvec`, and the recall query must cast the way the index was built.
_HNSW_MAX_VECTOR_DIM = 2000


def _owned_by(
    column: ColumnElement[str | None] | Any, owner_key: str | None
) -> ColumnElement[bool]:
    """ "Belongs to this owner", with `NULL` meaning the organization's store."""
    return column.is_(None) if owner_key is None else column == owner_key


def _readable(
    column: ColumnElement[str | None] | Any, read_keys: Sequence[str | None]
) -> ColumnElement[bool]:
    """ "Readable in this run": any of the stores the run's audience admits.

    `read_keys` comes from `MemoryAudience.read_keys`, which is what decides that
    a person's store is reachable only where that person is the sole listener and
    a room's only inside that room. Isolation holds because those keys are derived
    server-side and never named by the model, so no arm of this `OR` can reach a
    store the run was not admitted to (#788).
    """
    return or_(*(_owned_by(column, key) for key in read_keys))


def _owner_kind_filter(
    column: ColumnElement[str | None] | Any, owners: OwnerFilter
) -> ColumnElement[bool] | None:
    """The operator listing's owner filter, or `None` for "every store".

    Matched on the prefixes `app.db.models.memory` writes, so the three kinds an
    operator can filter by are the three the column can hold - a listing that
    silently spanned two kinds is how a per-person filter would show a room's
    notes to somebody auditing one employee's memory.
    """
    if owners == "all":
        return None
    if owners == MemoryOwnerKind.ORG:
        return column.is_(None)
    if owners == MemoryOwnerKind.ROOM:
        return column.startswith(ROOM_PREFIX)
    return column.startswith(PERSON_PREFIX)


async def get(db: AsyncSession, file_id: UUID, *, organization_id: UUID) -> AgentMemoryFile | None:
    result = await db.execute(
        select(AgentMemoryFile).where(
            AgentMemoryFile.id == file_id,
            AgentMemoryFile.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def get_by_name(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    name: str,
) -> AgentMemoryFile | None:
    """One file by name within a single store — the runtime read/edit lookup."""
    result = await db.execute(
        select(AgentMemoryFile).where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _owned_by(AgentMemoryFile.owner_key, owner_key),
            AgentMemoryFile.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_readable(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    limit: int = 200,
) -> list[AgentMemoryFile]:
    """Every file this run may read, newest first.

    The runtime index behind `list_memory`, spanning exactly the stores the run's
    audience admits. Capped at `limit` and ordered newest-first so a long-lived
    store hands the model what it learned last rather than the alphabetically-first
    rows; `updated_at` is null until a row is edited, so it falls back to
    `created_at`, which never is.
    """
    result = await db.execute(
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _readable(AgentMemoryFile.owner_key, read_keys),
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


async def get_readable_by_name(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    name: str,
) -> AgentMemoryFile | None:
    """One readable file by name, the most specific store winning a name clash.

    A name may exist in several of the stores a run reads - they are distinct rows,
    since the unique index treats different owner keys (a NULL among them) as
    different stores - so the tie is broken on `read_keys` order, which is the
    caller's precedence: this person's copy, then this room's, then the
    organization's. Encoding it as a `CASE` rather than re-deriving it here keeps
    one definition of "most specific" instead of two that can disagree.
    """
    precedence = case(
        *(
            (_owned_by(AgentMemoryFile.owner_key, key), position)
            for position, key in enumerate(read_keys)
        ),
        else_=len(read_keys),
    )
    result = await db.execute(
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _readable(AgentMemoryFile.owner_key, read_keys),
            AgentMemoryFile.name == name,
        )
        .order_by(precedence.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None = None,
    owners: OwnerFilter | None = None,
    search: str | None = None,
    sort: MemorySort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentMemoryFile], int]:
    """A page of an agent's memory files and the total — the operator index.

    `owners` filters by *kind* of owner and is the dashboard's tab strip
    (`all`/`org`/`person`/`room`); `owner_key` narrows to one specific store,
    which is how an operator audits a single person or a single channel. Passing
    neither lists the organization's own store, the same as `owner_key=None`.
    Search covers name and description, the two things a person remembers about a
    file; the body is what the model reads. "updated" sorting falls back to
    `created_at`, which is never null.
    """
    where = [
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.agent_id == agent_id,
    ]
    if owners is not None:
        kind_filter = _owner_kind_filter(AgentMemoryFile.owner_key, owners)
        if kind_filter is not None:
            where.append(kind_filter)
    else:
        where.append(_owned_by(AgentMemoryFile.owner_key, owner_key))
    if search:
        where.append(
            or_(
                contains_ci(AgentMemoryFile.name, search),
                contains_ci(AgentMemoryFile.description, search),
            )
        )
    # `id` is the stable final key: names repeat across stores and timestamps
    # collide, and OFFSET/LIMIT over a tie drops or repeats rows between pages.
    order_by = (
        (
            func.coalesce(AgentMemoryFile.updated_at, AgentMemoryFile.created_at).desc(),
            AgentMemoryFile.name.asc(),
            AgentMemoryFile.id.asc(),
        )
        if sort == "updated"
        else (AgentMemoryFile.name.asc(), AgentMemoryFile.id.asc())
    )
    items = await db.execute(
        select(AgentMemoryFile).where(*where).order_by(*order_by).offset(skip).limit(limit)
    )
    total = await db.scalar(select(func.count(AgentMemoryFile.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    name: str,
    description: str | None,
    content: str,
    content_format: str,
    kind: str,
    origin: str,
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
        origin=origin,
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


async def delete_all_files(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """Delete every memory file for one agent, in every store; returns the count.

    A set-based delete rather than a row-by-row loop: the danger-zone "clear all"
    is a single statement, and there are no ORM cascades on this table to miss.
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


@dataclass(frozen=True)
class FactHit:
    """One recalled fact and how close it was, detached from the session."""

    content: str
    score: float


async def create_fact(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None,
    content: str,
    embedding: list[float],
    origin: str,
) -> tuple[UUID, datetime]:
    """Write one fact and its vector; return the new row's id and `created_at`.

    Raw SQL because `embedding` has no SQLAlchemy type in this project (see
    `AgentMemoryFact`); pgvector parses the vector from the text form `str(list)`
    produces, the same as the RAG store's insert. `origin` is the caller's trust
    tier - `agent` from the runtime `remember`, `operator` from a management seed -
    and decides whether the fact may enter the shared brief. `id` is generated here
    and `created_at` is the column default, and both come back through `RETURNING`
    so an operator create can echo the stored row (the agent's `remember` ignores
    it).
    """
    result = await db.execute(
        text(
            "INSERT INTO agent_memory_facts "
            "(id, organization_id, agent_id, owner_key, content, embedding, origin) "
            "VALUES (:id, :organization_id, :agent_id, :owner, :content, :embedding, :origin) "
            "RETURNING id, created_at"
        ),
        {
            "id": uuid4(),
            "organization_id": organization_id,
            "agent_id": agent_id,
            "owner": owner_key,
            "content": content,
            "embedding": str(embedding),
            "origin": origin,
        },
    )
    row = result.one()
    return row[0], row[1]


async def recall_facts(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    query_embedding: list[float],
    limit: int = 5,
) -> list[FactHit]:
    """The nearest facts a run may recall, most-similar first.

    Cosine distance (`<=>`) over the HNSW index, scored `1 - distance` so higher
    is closer. The query vector is cast the same way the column is indexed - a
    `halfvec` past 2000 dimensions - or Postgres compares a halfvec against a
    vector and refuses the operator, exactly as the RAG search does. Scoped before
    the KNN to exactly the stores the run's audience admits, so a run only ever
    recalls from what it was admitted to; the keys are server-derived, so no arm
    can reach another person's or another room's store.

    `hnsw.iterative_scan` is on (pgvector >= 0.8) because the scope predicates are
    applied *after* the approximate scan: without it, on a populated multi-agent
    table the fixed candidate set the index returns can be mostly other agents'
    or other owners' rows, so a scoped recall would return fewer than `limit` - or
    nothing - even when the agent has matching facts. `strict_order` keeps exact
    distance order while it scans further to fill the limit.
    """
    dim = settings.rag.embeddings_config.dim
    wide = dim > _HNSW_MAX_VECTOR_DIM
    distance = f"(embedding::halfvec({dim}))" if wide else "embedding"
    query_expr = f"(:query_vec)::halfvec({dim})" if wide else ":query_vec"
    params: dict[str, Any] = {
        "organization_id": organization_id,
        "agent_id": agent_id,
        "query_vec": str(query_embedding),
        "limit": limit,
    }
    # One named parameter per key rather than an `IN`: the set is at most three
    # entries, and `NULL` (the organization store) has to be an `IS NULL` arm
    # anyway, so an array would still need the same union around it.
    arms: list[str] = []
    for position, key in enumerate(read_keys):
        if key is None:
            arms.append("owner_key IS NULL")
        else:
            arms.append(f"owner_key = :owner_{position}")
            params[f"owner_{position}"] = key
    scope_sql = f"({' OR '.join(arms)})"
    await db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    result = await db.execute(
        text(
            f"SELECT content, 1 - ({distance} <=> {query_expr}) AS score "
            "FROM agent_memory_facts "
            "WHERE organization_id = :organization_id AND agent_id = :agent_id "
            f"AND {scope_sql} "
            f"ORDER BY {distance} <=> {query_expr} "
            "LIMIT :limit"
        ),
        params,
    )
    return [FactHit(content=row[0], score=float(row[1])) for row in result.fetchall()]


async def list_brief_facts(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    read_keys: Sequence[str | None],
    self_key: str | None,
    limit: int,
) -> list[AgentMemoryFact]:
    """The facts safe to inject into the agent's standing brief - newest first.

    Narrower than what `recall` reads, and the difference is the whole point:
    `recall_facts` answers as a *tool result*, which a model weighs, while the
    brief is spliced into the agent's own instructions, which it obeys. So the
    brief carries only content whose author could not use it to steer somebody
    else's run:

    - **the reader's own store** (`self_key`) - whatever is in it, whoever wrote
      it, it can only ever influence that one person's runs. This is the arm that
      makes memory feel present without a tool call.
    - **anything an operator wrote**, in any store the run reads - a person
      vouched for it.

    Everything else is agent-authored content in a *shared* store - the
    organization's or a room's - which is user-influenced text that would
    otherwise reach the prompt of everyone the agent serves. It stays recall-only.

    A room is why this is stated as a rule rather than as "personal plus operator
    shared": a room's store is self-scoped to nobody. Anna's crafted sentence
    written into `room:…` would be read back as instructions in Bob's run in the
    same channel, so the earlier shape - trust anything non-NULL - would have
    handed one colleague a prompt-injection channel into another's (#788).
    """
    operator_authored = and_(
        _readable(AgentMemoryFact.owner_key, read_keys),
        AgentMemoryFact.origin == MemoryOrigin.OPERATOR.value,
    )
    injectable = (
        operator_authored
        if self_key is None
        else or_(operator_authored, AgentMemoryFact.owner_key == self_key)
    )
    result = await db.execute(
        select(AgentMemoryFact)
        .where(
            AgentMemoryFact.organization_id == organization_id,
            AgentMemoryFact.agent_id == agent_id,
            injectable,
        )
        # `id` breaks a shared `created_at` tie, so the newest-first cap picks the same
        # set each request.
        .order_by(AgentMemoryFact.created_at.desc(), AgentMemoryFact.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_fact(
    db: AsyncSession, fact_id: UUID, *, organization_id: UUID
) -> AgentMemoryFact | None:
    result = await db.execute(
        select(AgentMemoryFact).where(
            AgentMemoryFact.id == fact_id,
            AgentMemoryFact.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def list_facts(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    owner_key: str | None = None,
    owners: OwnerFilter | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentMemoryFact], int]:
    """A page of an agent's facts and the total - the operator listing.

    Owner filtering matches `list_for_agent`: `owners` spans a kind of store,
    `owner_key` narrows to one. Search is a substring match on `content`, not a
    semantic one: a KNN query would embed the operator's text off the run's spend
    ledger (N4/BONUS-3), so semantic recall stays the agent's runtime tool. Newest
    first, because a fact has no name to sort by and what an operator scanning them
    wants is the latest.
    """
    where = [
        AgentMemoryFact.organization_id == organization_id,
        AgentMemoryFact.agent_id == agent_id,
    ]
    if owners is not None:
        kind_filter = _owner_kind_filter(AgentMemoryFact.owner_key, owners)
        if kind_filter is not None:
            where.append(kind_filter)
    else:
        where.append(_owned_by(AgentMemoryFact.owner_key, owner_key))
    if search:
        where.append(contains_ci(AgentMemoryFact.content, search))
    items = await db.execute(
        select(AgentMemoryFact)
        .where(*where)
        # `id` breaks a shared `created_at` tie, or paging drops or repeats facts.
        .order_by(AgentMemoryFact.created_at.desc(), AgentMemoryFact.id.asc())
        .offset(skip)
        .limit(limit)
    )
    total = await db.scalar(select(func.count(AgentMemoryFact.id)).where(*where))
    return list(items.scalars().all()), total or 0


async def delete_fact(db: AsyncSession, fact: AgentMemoryFact) -> None:
    await db.delete(fact)
    await db.flush()


async def delete_all_facts(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """Delete every fact for one agent, in every store; returns the count."""
    result = await db.execute(
        sa_delete(AgentMemoryFact).where(
            AgentMemoryFact.organization_id == organization_id,
            AgentMemoryFact.agent_id == agent_id,
        )
    )
    await db.flush()
    # A DML statement returns a `CursorResult` with `rowcount`, though `execute`
    # is typed to return a `Result` without it (see `resource_grant`).
    return result.rowcount or 0  # ty: ignore[unresolved-attribute]
