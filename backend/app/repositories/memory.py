"""Agent-memory-file repository (PostgreSQL async).

Every read is scoped to an agent and a partition. The partition key is nullable
and `NULL` means the one shared store, so "in this partition" is `col IS NULL`
for the shared case and `col = key` otherwise — a plain `col = NULL` is never
true and would make the shared partition silently unreadable. The unique index
enforces the same rule at write time with `NULLS NOT DISTINCT`, so a read and a
uniqueness check agree on what "the same partition" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, and_, func, or_, select, text
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.memory import AgentMemoryFact, AgentMemoryFile, MemoryOrigin
from app.repositories._search import contains_ci

MemorySort = Literal["name", "updated"]

# pgvector's HNSW index takes a `vector` column up to this width; past it the column
# is `halfvec`, and the recall query must cast the way the index was built.
_HNSW_MAX_VECTOR_DIM = 2000


def _in_partition(scope_key: str | None) -> ColumnElement[bool]:
    """ "In this partition", with `NULL` meaning the one shared store."""
    column = AgentMemoryFile.end_user_scope_key
    return column.is_(None) if scope_key is None else column == scope_key


def _readable(personal_key: str | None) -> ColumnElement[bool]:
    """ "Readable in this run": the shared store, plus one person's when the run has
    an identified person.

    The two-tier read - a run always sees the agent's shared store, and when it
    carries an end-user it also sees that person's personal store. `personal_key`
    is `None` on a surface with no identified person, and the run reads shared
    alone. Isolation holds because the key is derived server-side, never named by
    the model, so the `= personal_key` arm can only ever match the current person's
    rows (#788)."""
    column = AgentMemoryFile.end_user_scope_key
    if personal_key is None:
        return column.is_(None)
    return or_(column.is_(None), column == personal_key)


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
    end_user_scope_key: str | None,
    name: str,
) -> AgentMemoryFile | None:
    """One file by name within a single partition — the runtime read/edit lookup."""
    result = await db.execute(
        select(AgentMemoryFile).where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _in_partition(end_user_scope_key),
            AgentMemoryFile.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_readable(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    personal_key: str | None,
    limit: int = 200,
) -> list[AgentMemoryFile]:
    """Every file this run may read - shared plus the current person's - newest first.

    The runtime index behind `list_memory`: the agent's shared store, unioned with
    the end-user's personal store when the run has one (`personal_key`). Capped at
    `limit` and ordered newest-first so a long-lived store hands the model what it
    learned last rather than the alphabetically-first rows; `updated_at` is null
    until a row is edited, so it falls back to `created_at`, which never is.
    """
    result = await db.execute(
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _readable(personal_key),
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
    personal_key: str | None,
    name: str,
) -> AgentMemoryFile | None:
    """One readable file by name, the personal copy winning a cross-tier name clash.

    `read_memory` under the two-tier model: a name may exist in both the shared and
    the personal store - they are distinct rows, since the unique index treats a
    NULL and a non-NULL scope as different partitions - and the personal one is the
    current person's own, so it is returned first. `personal_key=None` reads shared
    alone.
    """
    result = await db.execute(
        select(AgentMemoryFile)
        .where(
            AgentMemoryFile.organization_id == organization_id,
            AgentMemoryFile.agent_id == agent_id,
            _readable(personal_key),
            AgentMemoryFile.name == name,
        )
        # Personal (non-NULL scope) before shared (NULL), so a name in both tiers
        # resolves to the current person's copy.
        .order_by(AgentMemoryFile.end_user_scope_key.is_(None).asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_for_agent(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    scope_key: str | None = None,
    all_partitions: bool = False,
    scoped_only: bool = False,
    search: str | None = None,
    sort: MemorySort = "name",
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentMemoryFile], int]:
    """A page of an agent's memory files and the total — the operator index.

    `all_partitions` lists every partition at once (the management "All" filter);
    `scoped_only` lists every per-user partition and not the shared store (the
    "Per-user" filter); otherwise the listing is confined to `scope_key`
    (`None` = the shared store). Search covers name and description, the two
    things a person remembers about a file; the body is what the model reads.
    "updated" sorting falls back to `created_at`, which is never null.
    """
    where = [
        AgentMemoryFile.organization_id == organization_id,
        AgentMemoryFile.agent_id == agent_id,
    ]
    if scoped_only:
        where.append(AgentMemoryFile.end_user_scope_key.is_not(None))
    elif not all_partitions:
        where.append(_in_partition(scope_key))
    if search:
        where.append(
            or_(
                contains_ci(AgentMemoryFile.name, search),
                contains_ci(AgentMemoryFile.description, search),
            )
        )
    # `id` is the stable final key: names repeat across partitions and timestamps
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
    end_user_scope_key: str | None,
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
        end_user_scope_key=end_user_scope_key,
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
    """Delete every memory file for one agent, in every partition; returns the count.

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


def _fact_scope(scope_key: str | None) -> ColumnElement[bool]:
    column = AgentMemoryFact.end_user_scope_key
    return column.is_(None) if scope_key is None else column == scope_key


async def create_fact(
    db: AsyncSession,
    *,
    organization_id: UUID,
    agent_id: UUID,
    end_user_scope_key: str | None,
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
            "(id, organization_id, agent_id, end_user_scope_key, content, embedding, origin) "
            "VALUES (:id, :organization_id, :agent_id, :scope, :content, :embedding, :origin) "
            "RETURNING id, created_at"
        ),
        {
            "id": uuid4(),
            "organization_id": organization_id,
            "agent_id": agent_id,
            "scope": end_user_scope_key,
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
    personal_key: str | None,
    query_embedding: list[float],
    limit: int = 5,
) -> list[FactHit]:
    """The nearest facts a run may recall, most-similar first.

    Cosine distance (`<=>`) over the HNSW index, scored `1 - distance` so higher
    is closer. The query vector is cast the same way the column is indexed - a
    `halfvec` past 2000 dimensions - or Postgres compares a halfvec against a
    vector and refuses the operator, exactly as the RAG search does. Scoped before
    the KNN to the shared store, unioned with the current person's when the run has
    one (`personal_key`), so a run only ever recalls from stores it was admitted
    to; the key is server-derived, so the union can never reach another person's.

    `hnsw.iterative_scan` is on (pgvector >= 0.8) because the scope predicates are
    applied *after* the approximate scan: without it, on a populated multi-agent
    table the fixed candidate set the index returns can be mostly other agents'
    or partitions' rows, so a scoped recall would return fewer than `limit` - or
    nothing - even when the agent has matching facts. `strict_order` keeps exact
    distance order while it scans further to fill the limit.
    """
    dim = settings.rag.embeddings_config.dim
    wide = dim > _HNSW_MAX_VECTOR_DIM
    distance = f"(embedding::halfvec({dim}))" if wide else "embedding"
    query_expr = f"(:query_vec)::halfvec({dim})" if wide else ":query_vec"
    scope_sql = (
        "end_user_scope_key IS NULL"
        if personal_key is None
        else "(end_user_scope_key IS NULL OR end_user_scope_key = :scope)"
    )
    params: dict[str, Any] = {
        "organization_id": organization_id,
        "agent_id": agent_id,
        "query_vec": str(query_embedding),
        "limit": limit,
    }
    if personal_key is not None:
        params["scope"] = personal_key
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
    personal_key: str | None,
    limit: int,
) -> list[AgentMemoryFact]:
    """The facts safe to inject into the agent's standing brief - newest first.

    Narrower than what `recall` reads. `recall_facts` returns the whole union as a
    tool result, which is untrusted-safe; the brief is spliced into the agent's
    instructions, so it carries only content that is safe there: a person's own
    facts (self-scoped - whoever authored them, they can influence only that
    person's runs) and operator-authored shared ones (a person vouched for them).
    An agent-authored *shared* fact is user-influenced content that would otherwise
    reach every end-user's prompt, so it is excluded and stays recall-only - the
    fact analogue of a file's `origin` trust tier (#788). The key is server-derived,
    so the personal arm can never reach another person's store.
    """
    operator_shared = and_(
        AgentMemoryFact.end_user_scope_key.is_(None),
        AgentMemoryFact.origin == MemoryOrigin.OPERATOR.value,
    )
    injectable = operator_shared
    if personal_key is not None:
        injectable = or_(operator_shared, AgentMemoryFact.end_user_scope_key == personal_key)
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
    scope_key: str | None = None,
    all_partitions: bool = False,
    scoped_only: bool = False,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[AgentMemoryFact], int]:
    """A page of an agent's facts and the total - the operator listing.

    Partition filtering matches `list_for_agent`: `all_partitions` spans every
    store, `scoped_only` every per-user store, otherwise `scope_key` alone.
    Search is a substring match on `content`, not a semantic one: a KNN query
    would embed the operator's text off the run's spend ledger (N4/BONUS-3), so
    semantic recall stays the agent's runtime tool. Newest first, because a fact
    has no name to sort by and what an operator scanning them wants is the latest.
    """
    where = [
        AgentMemoryFact.organization_id == organization_id,
        AgentMemoryFact.agent_id == agent_id,
    ]
    if scoped_only:
        where.append(AgentMemoryFact.end_user_scope_key.is_not(None))
    elif not all_partitions:
        where.append(_fact_scope(scope_key))
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


async def set_fact_origin(
    db: AsyncSession, *, fact: AgentMemoryFact, origin: str
) -> AgentMemoryFact:
    """Change a fact's trust tier - the promote write - and return the refreshed row.

    A fact's only mutation: its content is never amended, only replaced, so unlike a
    file's `update` this takes just the one field. `embedding` is not a mapped column
    (see `AgentMemoryFact`), so a plain attribute set, flush and refresh leaves the
    stored vector untouched.
    """
    fact.origin = origin
    db.add(fact)
    await db.flush()
    await db.refresh(fact)
    return fact


async def delete_fact(db: AsyncSession, fact: AgentMemoryFact) -> None:
    await db.delete(fact)
    await db.flush()


async def delete_all_facts(db: AsyncSession, *, organization_id: UUID, agent_id: UUID) -> int:
    """Delete every fact for one agent, in every partition; returns the count."""
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
