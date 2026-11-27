"""Which stored chunks an embedding test re-embeds, read from a real pgvector table.

The pick is the test's whole sample: the two shortest chunks of at least 100
characters plus the longest, inside the base's own scope. A chunk from another
tenant or base reaching it would send that text to an endpoint the owner never
chose, so the scope is asserted on real rows.
"""

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.vector_tables import VectorScope
from app.services.rag.config import RAGSettings
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

COLLECTION = "probe_corpus"
TABLE = f"rag_{COLLECTION}"
ORG = uuid.uuid4()
FLOOR = 100


def _kb(organization_id: uuid.UUID | None = ORG) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=COLLECTION,
        scope=KBScope.ORG.value,
        collection_name=COLLECTION,
        embedding_model="m",
        embedding_dim=3,
        organization_id=organization_id,
    )


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.settings = RAGSettings()
    return store


@pytest.fixture(autouse=True)
async def _table(engine: AsyncEngine) -> AsyncGenerator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        await conn.execute(
            text(
                f"CREATE TABLE {TABLE} (id text PRIMARY KEY, parent_doc_id text, "
                "content text, embedding vector(3), metadata jsonb)"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def _put(
    engine: AsyncEngine,
    chunk_id: str,
    content: str | None,
    *,
    kb: KnowledgeBase | None = None,
    tenant: uuid.UUID | None = ORG,
    vector: str = "[0.1,0.2,0.3]",
) -> None:
    meta: dict[str, str] = {}
    if tenant is not None:
        meta["organization_id"] = str(tenant)
    if kb is not None:
        meta["knowledge_base_id"] = str(kb.id)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
                "VALUES (:id, 'doc', :content, CAST(:vector AS vector), CAST(:meta AS jsonb))"
            ),
            {"id": chunk_id, "content": content, "vector": vector, "meta": json.dumps(meta)},
        )


async def _picked(engine: AsyncEngine, scope: VectorScope) -> list[str]:
    chunks = await _store(engine).probe_chunks(COLLECTION, scope, min_length=FLOOR, shortest=2)
    return [chunk.content for chunk in chunks]


async def test_two_shortest_above_the_floor_and_the_longest_are_picked(
    engine: AsyncEngine,
) -> None:
    kb = _kb()
    await _put(engine, "a", "x" * 20, kb=kb)  # under the floor and not the longest
    await _put(engine, "b", "y" * 100, kb=kb)
    await _put(engine, "c", "z" * 150, kb=kb)
    await _put(engine, "d", "w" * 400, kb=kb)
    await _put(engine, "e", "v" * 900, kb=kb)

    assert await _picked(engine, kb.vector_scope) == ["y" * 100, "z" * 150, "v" * 900]


async def test_a_chunk_of_exactly_the_floor_counts_and_one_under_does_not(
    engine: AsyncEngine,
) -> None:
    kb = _kb()
    await _put(engine, "a", "x" * 99, kb=kb)
    await _put(engine, "b", "y" * 100, kb=kb)
    await _put(engine, "c", "z" * 300, kb=kb)

    # 99 is under the floor and not the longest; 100 qualifies; 300 is the longest.
    assert await _picked(engine, kb.vector_scope) == ["y" * 100, "z" * 300]


async def test_the_stored_vector_comes_back_with_the_text(engine: AsyncEngine) -> None:
    kb = _kb()
    await _put(engine, "a", "x" * 120, kb=kb, vector="[0.5,0.25,0.125]")

    (chunk,) = await _store(engine).probe_chunks(
        COLLECTION, kb.vector_scope, min_length=FLOOR, shortest=2
    )

    assert chunk.embedding == [0.5, 0.25, 0.125]


async def test_an_unfiled_readable_chunk_is_a_candidate(engine: AsyncEngine) -> None:
    kb = _kb()
    assert kb.vector_scope.takes_unfiled
    await _put(engine, "a", "u" * 130, kb=None)

    assert await _picked(engine, kb.vector_scope) == ["u" * 130]


@pytest.mark.security
async def test_another_bases_or_tenants_chunks_are_never_picked(engine: AsyncEngine) -> None:
    kb, other_kb = _kb(), _kb()
    await _put(engine, "a", "m" * 200, kb=kb)
    await _put(engine, "b", "o" * 300, kb=other_kb)
    await _put(engine, "c", "t" * 500, kb=kb, tenant=uuid.uuid4())
    await _put(engine, "d", "n" * 700, kb=None, tenant=None)

    scope = VectorScope(tenant=ORG, knowledge_base_id=kb.id, takes_unfiled=False)
    assert await _picked(engine, scope) == ["m" * 200]


async def test_a_base_with_only_short_chunks_is_probed_on_its_longest_alone(
    engine: AsyncEngine,
) -> None:
    kb = _kb()
    for index, length in enumerate((10, 40, 99)):
        await _put(engine, f"s{index}", "s" * length, kb=kb)

    assert await _picked(engine, kb.vector_scope) == ["s" * 99]


async def test_a_missing_table_yields_nothing(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE {TABLE}"))

    assert await _picked(engine, _kb().vector_scope) == []


async def test_empty_and_null_chunks_are_never_picked(engine: AsyncEngine) -> None:
    kb = _kb()
    await _put(engine, "a", "", kb=kb)
    await _put(engine, "b", None, kb=kb)
    await _put(engine, "c", "k" * 110, kb=kb)

    assert await _picked(engine, kb.vector_scope) == ["k" * 110]


async def test_ties_are_broken_by_id_so_the_pick_is_reproducible(engine: AsyncEngine) -> None:
    kb = _kb()
    for chunk_id, vector in (("t3", "[3,0,0]"), ("t1", "[1,0,0]"), ("t2", "[2,0,0]")):
        await _put(engine, chunk_id, "q" * 120, kb=kb, vector=vector)

    chunks = await _store(engine).probe_chunks(
        COLLECTION, kb.vector_scope, min_length=FLOOR, shortest=2
    )

    # The two shortest are t1 and t2; the longest tie is t1 again, so it is not repeated.
    assert [chunk.embedding for chunk in chunks] == [[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
