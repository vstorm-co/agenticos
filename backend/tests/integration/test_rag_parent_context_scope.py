"""Parent-context expansion never crosses tenant scope on a shared table (#1651).

Small-to-big retrieval pulls a matched chunk's siblings back out of the store on
the return path. `rag_<collection>` runtime tables are keyed by collection *name*
only, so two organizations that pick the same name share one physical table and
can even collide on `parent_doc_id`. This seeds one shared table with Org A's and
Org B's chunks under the *same* document id and proves that expanding Org A's
match returns only Org A's chunk content - the expansion read carries the same
tenant conjunct every other read does. A mock cannot show this: the guarantee is
a `metadata->>'organization_id'` predicate, and only a real database carrying the
values proves the predicate isolates real rows.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.services.rag.config import RAGSettings
from app.services.rag.filters import TenantScope
from app.services.rag.models import ParentContextMode
from app.services.rag.retrieval import RetrievalService
from app.services.rag.vectorstore import PgVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"
ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
DOC = "doc-shared"  # deliberately identical across tenants


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.settings = RAGSettings()
    store.embedder = None  # type: ignore[assignment]
    store._resolver = _no_resolution  # type: ignore[assignment]
    # The query does not reach a provider; the scope is what these tests exercise.
    embedder = MagicMock(embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]))
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]
    return store


async def _insert(store: PgVectorStore, *, tenant: uuid.UUID, prefix: str, chunk_num: int) -> None:
    meta: dict[str, object] = {
        "filename": "handbook.pdf",
        "page_num": 0,
        "chunk_num": chunk_num,
        "organization_id": str(tenant),
    }
    insert = (
        f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
        "VALUES (:id, :pid, :content, CAST(:emb AS vector), CAST(:meta AS jsonb))"
    )
    async with store.async_session() as session:
        await session.execute(
            text(insert),
            {
                "id": f"{tenant}-{chunk_num}",
                "pid": DOC,
                "content": f"{prefix}-c{chunk_num}",
                "emb": "[0.1,0.2,0.3]",
                "meta": json.dumps(meta),
            },
        )
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def _seed_both_tenants(store: PgVectorStore) -> None:
    await store._ensure_collection(COLLECTION)
    for chunk_num in range(3):
        await _insert(store, tenant=ORG_A, prefix="A", chunk_num=chunk_num)
        await _insert(store, tenant=ORG_B, prefix="B", chunk_num=chunk_num)


async def test_parent_expansion_returns_only_the_searching_tenants_chunks(
    engine: AsyncEngine,
) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)
    service = RetrievalService(vector_store=store, settings=RAGSettings())

    results = await service.retrieve(
        query="anything",
        collection_name=COLLECTION,
        scope=TenantScope(organization_id=ORG_A),
        limit=1,
        parent_context=ParentContextMode.PARENT,
    )

    assert len(results) == 1
    expanded = results[0].expanded_content
    assert expanded is not None
    # The whole of Org A's document, and none of Org B's - even though both live
    # under the same parent_doc_id in the same physical table.
    assert expanded.split("\n\n") == ["A-c0", "A-c1", "A-c2"]
    assert "B-c" not in expanded


async def test_window_expansion_is_scoped_to_the_searching_tenant(engine: AsyncEngine) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)
    service = RetrievalService(vector_store=store, settings=RAGSettings())

    results = await service.retrieve(
        query="anything",
        collection_name=COLLECTION,
        scope=TenantScope(organization_id=ORG_B),
        limit=1,
        parent_context=ParentContextMode.WINDOW,
    )

    assert len(results) == 1
    expanded = results[0].expanded_content
    assert expanded is not None
    # Every neighbour pulled into the window belongs to Org B.
    assert all(piece.startswith("B-c") for piece in expanded.split("\n\n"))
    assert "A-c" not in expanded
