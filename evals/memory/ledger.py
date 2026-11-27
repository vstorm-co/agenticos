"""Replay transcript chunks through the production AgenticOS ledger reader."""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from inspect import signature
from time import perf_counter
from typing import TypedDict
from uuid import UUID, uuid4, uuid5

from dataset import Query
from retrieval import Evidence, Retrieved
from sqlalchemy import delete, insert, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.memory_keys import person_owner_key
from app.db.models.memory_claim import MemoryClaim
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories.memory_claim import ClaimScope
from app.services.memory._claims import recall

CHUNK_CHARS = 600
LOGICAL_CLOCK = datetime(2026, 1, 1, tzinfo=UTC)


class ClaimRow(TypedDict):
    id: UUID
    organization_id: UUID
    scope_key: str
    statement: str
    observed_at: datetime
    effective_from: datetime
    source_conversation_id: UUID


def disposable_engine(dsn: str) -> AsyncEngine:
    try:
        url = make_url(dsn)
    except ArgumentError:
        raise ValueError("Set MEMORY_BENCH_AGENTICOS_DSN to a local benchmark database.") from None
    if (
        url.drivername != "postgresql+asyncpg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("memory_bench")
        or url.query
    ):
        raise ValueError("Use a local postgresql+asyncpg DSN for a memory_bench* database.")
    return create_async_engine(url, hide_parameters=True)


@asynccontextmanager
async def isolated_scope(
    engine: AsyncEngine, *, committed: bool = False
) -> AsyncGenerator[tuple[AsyncSession, UUID, ClaimScope]]:
    async with AsyncSession(engine) as db:
        user_id, org_id = uuid4(), uuid4()
        db.add(User(id=user_id, email=f"{user_id}@memory-bench.invalid"))
        await db.flush()
        db.add(
            Organization(
                id=org_id,
                name="Memory benchmark",
                slug=f"mem-bench-{org_id}",
                created_by_user_id=user_id,
            )
        )
        await db.flush()
        try:
            yield db, org_id, ClaimScope(person_owner_key(user_id))
        finally:
            await db.rollback()
            if committed:
                # Delete only this run's synthetic tenant and its unique test member.
                await db.execute(delete(Organization).where(Organization.id == org_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()


async def insert_rows(
    db: AsyncSession,
    organization_id: UUID,
    scope: ClaimScope,
    rows: Iterable[tuple[UUID, str, datetime]],
) -> None:
    batch: list[ClaimRow] = []
    for index, (source, statement, date) in enumerate(rows, 1):
        # Stable relative tie order inside a unique per-transaction namespace.
        batch.append(
            ClaimRow(
                id=UUID(int=(organization_id.int & ~0xFFFFFFFF) | index),
                organization_id=organization_id,
                scope_key=scope.scope_key,
                statement=statement,
                observed_at=date,
                effective_from=date,
                source_conversation_id=source,
            )
        )
        if len(batch) == 2_000:
            await db.execute(insert(MemoryClaim), batch)
            batch.clear()
    if batch:
        await db.execute(insert(MemoryClaim), batch)


async def replay(engine: AsyncEngine, query: Query, top_k: int, *, legacy: bool) -> Retrieved:
    if legacy == ("as_of" in signature(recall).parameters):
        raise ValueError("Selected ledger arm does not match the backend checkout.")
    async with isolated_scope(engine) as (db, organization_id, scope):
        started = perf_counter()
        sources = {session.id: uuid5(organization_id, session.id) for session in query.sessions}
        source_ids = {value: key for key, value in sources.items()}
        rows = (
            (
                sources[session.id],
                f"{turn.role}: {turn.content[offset : offset + CHUNK_CHARS]}",
                session.date,
            )
            for session in query.sessions
            for turn in session.turns
            for offset in range(0, len(turn.content), CHUNK_CHARS)
        )
        await insert_rows(db, organization_id, scope, rows)
        indexed = perf_counter()
        dates = {} if legacy else {"as_of": query.date}
        hits = await recall(
            db,
            organization_id=organization_id,
            scopes=[scope],
            query=query.question,
            limit=top_k,
            **dates,
        )
        retrieved = perf_counter()
        evidence = [
            Evidence(
                source_id=source_ids.get(row.source_conversation_id)
                if row.source_conversation_id
                else None,
                text=row.statement,
                date=row.observed_at,
            )
            for row in hits
        ]
        return Retrieved(evidence, (indexed - started) * 1_000, (retrieved - indexed) * 1_000, 0.0)
