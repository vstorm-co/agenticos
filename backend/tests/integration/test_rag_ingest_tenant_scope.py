"""Org A cannot reach Org B's rows on a shared-named table (#1684).

`rag_<collection>` runtime tables are keyed by collection *name* only, and a
name is not unique across tenants - two organizations that pick the same name
share one physical table. The ingestion replace/dedup path looked a document up
and deleted it with no tenant predicate, so an ingest into a shared-named
collection could find, replace and DELETE a document belonging to a different
tenant, and a search could read its chunk content back.

This seeds one physical table with two tenants' documents that deliberately
collide on `source_path`, `filename` and `content_hash`, and proves the caller
of each row-level op - passing the collection's own tenant - sees and touches
only its own rows. A mock could not: the whole defect is a missing SQL
predicate, and only a real database carrying the `metadata->>'organization_id'`
values shows the predicate isolating real rows. The precedence and the SQL shape
are pinned in the unit suite (`tests/test_rag_ingest_tenant_scope.py`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.services.rag.models import SearchResult
from app.services.rag.vectorstore import PgVectorStore

# Every test here is a tenant-isolation refusal, so the whole module carries the
# security marker the refusal report collects.
pytestmark = [pytest.mark.anyio, pytest.mark.security]

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"
ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
SOURCE_PATH = "/srv/sync/handbook.pdf"
CONTENT_HASH = "hash-shared"


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    """The row ops take an explicit tenant, so resolution is unused here; only
    `_ensure_collection` reads the store's own default width through it."""
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.embedder = None  # type: ignore[assignment]  # unread for DDL and the scoped ops
    store._resolver = _no_resolution  # type: ignore[assignment]
    return store


async def _insert(
    store: PgVectorStore,
    *,
    doc_id: str,
    tenant: uuid.UUID | None,
    source_path: str = SOURCE_PATH,
    filename: str = "handbook.pdf",
    content_hash: str = CONTENT_HASH,
    embedding: str = "[0.1,0.2,0.3]",
) -> None:
    meta: dict[str, str] = {
        "source_path": source_path,
        "filename": filename,
        "content_hash": content_hash,
    }
    if tenant is not None:
        meta["organization_id"] = str(tenant)
    insert = (
        f"INSERT INTO {TABLE} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
        "VALUES (:id, :pid, :content, CAST(:emb AS vector), CAST(:meta AS jsonb))"
    )
    async with store.async_session() as session:
        await session.execute(
            text(insert),
            {
                "id": f"{doc_id}-0",
                "pid": doc_id,
                "content": f"content of {doc_id}",
                "emb": embedding,
                "meta": json.dumps(meta),
            },
        )
        await session.commit()


async def _parent_ids(store: PgVectorStore) -> set[str]:
    async with store.async_session() as session:
        result: Result = await session.execute(text(f"SELECT parent_doc_id FROM {TABLE}"))  # noqa: S608
        return {row[0] for row in result.fetchall()}


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def _seed_both_tenants(store: PgVectorStore) -> None:
    """One shared table holding Org A's and Org B's colliding documents."""
    await store._ensure_collection(COLLECTION)
    await _insert(store, doc_id="doc-a", tenant=ORG_A)
    await _insert(store, doc_id="doc-b", tenant=ORG_B)


async def test_org_a_does_not_find_org_bs_colliding_document(engine: AsyncEngine) -> None:
    """The security core: a source_path/filename/content_hash collision must not
    let Org A match Org B's document - the lookup the replace path deletes on."""
    store = _store(engine)
    await store._ensure_collection(COLLECTION)
    await _insert(store, doc_id="doc-b", tenant=ORG_B)

    hit = await store.find_existing_document(
        COLLECTION, source_path=SOURCE_PATH, content_hash=CONTENT_HASH, tenant=ORG_A
    )

    assert hit is None


async def test_org_a_finds_only_its_own_document(engine: AsyncEngine) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)

    hit = await store.find_existing_document(
        COLLECTION, source_path=SOURCE_PATH, content_hash=CONTENT_HASH, tenant=ORG_A
    )

    assert hit is not None
    assert hit.document_id == "doc-a"


async def test_org_a_cannot_delete_org_bs_document(engine: AsyncEngine) -> None:
    """Even naming Org B's own vector id, a delete scoped to Org A removes
    nothing - the id belongs to a row Org A may not touch."""
    store = _store(engine)
    await _seed_both_tenants(store)

    await store.delete_document(COLLECTION, "doc-b", ORG_A)

    assert await _parent_ids(store) == {"doc-a", "doc-b"}


async def test_org_a_deletes_its_own_document(engine: AsyncEngine) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)

    await store.delete_document(COLLECTION, "doc-a", ORG_A)

    assert await _parent_ids(store) == {"doc-b"}


async def test_listing_and_count_are_scoped_per_tenant(engine: AsyncEngine) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)

    a_docs = await store.get_documents(COLLECTION, ORG_A)
    b_docs = await store.get_documents(COLLECTION, ORG_B)
    a_info = await store.get_collection_info(COLLECTION, tenant=ORG_A)

    assert [d.document_id for d in a_docs] == ["doc-a"]
    assert [d.document_id for d in b_docs] == ["doc-b"]
    assert a_info.total_vectors == 1


async def test_reading_chunks_is_scoped_per_tenant(engine: AsyncEngine) -> None:
    store = _store(engine)
    await _seed_both_tenants(store)

    a_chunks = await store.get_document_chunks(COLLECTION, "doc-b", ORG_A)

    assert a_chunks == []


async def test_search_does_not_leak_another_tenants_chunk_content(engine: AsyncEngine) -> None:
    """A shared collection name must not return Org B's chunk content to Org A."""
    store = _store(engine)
    await _seed_both_tenants(store)
    # The embedder is stubbed so the query does not go to a provider; the search
    # scopes its rows by the tenant it is given.
    embedder = MagicMock(embed_query=MagicMock(return_value=[0.1, 0.2, 0.3]))
    store._for_collection = AsyncMock(return_value=(embedder, 3))  # type: ignore[method-assign]

    results: list[SearchResult] = await store.search(COLLECTION, "anything", limit=10, tenant=ORG_A)

    contents = {r.content for r in results}
    assert contents == {"content of doc-a"}


async def test_a_deployment_wide_collection_sees_only_untagged_rows(engine: AsyncEngine) -> None:
    """A deployment-wide collection - an app-scoped base, a CLI or local-path
    ingest - carries no tenant: its `None` scope matches only rows with no
    organization tag, not Org A's or Org B's."""
    store = _store(engine)
    await store._ensure_collection(COLLECTION)
    await _insert(store, doc_id="doc-a", tenant=ORG_A)
    await _insert(store, doc_id="doc-none", tenant=None)

    hit = await store.find_existing_document(
        COLLECTION, source_path=SOURCE_PATH, content_hash=CONTENT_HASH, tenant=None
    )
    docs = await store.get_documents(COLLECTION, None)

    assert hit is not None and hit.document_id == "doc-none"
    assert [d.document_id for d in docs] == ["doc-none"]
