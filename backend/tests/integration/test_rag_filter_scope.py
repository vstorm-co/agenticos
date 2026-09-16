"""Scope + filter enforcement in the store, against a real pgvector Postgres.

The unit tests prove the WHERE conjuncts are assembled; these prove the SQL they
become actually restricts the rows - cross-tenant denial on a shared-named table,
the business dimensions, the impossible-date guard, and the facet - which only a
real database can answer.
"""

from __future__ import annotations

import random
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.services.rag.config import RAGSettings
from app.services.rag.filters import (
    RetrievalFilters,
    RetrievalQuery,
    TenantScope,
    UnscopedScope,
)
from app.services.rag.models import Document, DocumentMetadata, DocumentPage, DocumentPageChunk
from app.services.rag.vectorstore import PgVectorStore

pytestmark = [pytest.mark.anyio, pytest.mark.security]

_DIM = 3


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.settings = RAGSettings()
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    embedder = MagicMock(
        embed_document=MagicMock(
            side_effect=lambda doc: [[0.25] * _DIM for _ in doc.chunked_pages]
        ),
        embed_query=MagicMock(return_value=[0.25] * _DIM),
    )
    store._for_collection = AsyncMock(return_value=(embedder, _DIM))  # ty: ignore[invalid-assignment]
    return store


async def _insert(
    store: PgVectorStore,
    collection: str,
    *,
    org: uuid.UUID | None,
    source: str = "upload",
    document_type: str = "pdf",
    doc_date: str | None = None,
    organizational_unit: str | None = None,
    content: str = "chunk",
) -> str:
    metadata = DocumentMetadata(
        filename="handbook.pdf",
        filesize=10,
        filetype=document_type,
        organization_id=str(org) if org is not None else None,
        source=source,
        document_type=document_type,
        doc_date=doc_date,
        organizational_unit=organizational_unit,
    )
    document = Document(pages=[DocumentPage(page_num=1, content=content)], metadata=metadata)
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=content,
            chunk_num=0,
            page_num=1,
            content=content,
            parent_doc_id=document.id,
        )
    ]
    await store.insert_document(collection, document)
    return document.id


def _tenant(org: uuid.UUID, **filter_kwargs) -> RetrievalQuery:
    return RetrievalQuery(
        scope=TenantScope(organization_id=org), filters=RetrievalFilters(**filter_kwargs)
    )


async def _ids(store: PgVectorStore, collection: str, query_filter: RetrievalQuery) -> set[str]:
    results = await store.search(collection, "anything", query_filter, limit=50)
    return {r.parent_doc_id for r in results if r.parent_doc_id}


async def test_a_tenant_never_sees_another_orgs_chunks_on_a_shared_name(
    engine: AsyncEngine,
) -> None:
    collection = f"shared_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    mine = await _insert(store, collection, org=org_a)
    await _insert(store, collection, org=org_b)

    assert await _ids(store, collection, _tenant(org_a)) == {mine}


async def test_a_chunk_missing_the_tenant_is_never_returned(engine: AsyncEngine) -> None:
    collection = f"legacy_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org = uuid.uuid4()
    tagged = await _insert(store, collection, org=org)
    await _insert(store, collection, org=None)  # a legacy / local-sync chunk

    assert await _ids(store, collection, _tenant(org)) == {tagged}


async def test_the_unscoped_marker_reaches_every_chunk(engine: AsyncEngine) -> None:
    collection = f"maint_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    a = await _insert(store, collection, org=uuid.uuid4())
    b = await _insert(store, collection, org=None)

    query = RetrievalQuery(scope=UnscopedScope())
    assert await _ids(store, collection, query) == {a, b}


async def test_business_filters_narrow_within_the_tenant(engine: AsyncEngine) -> None:
    collection = f"biz_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org = uuid.uuid4()
    pdf_upload = await _insert(store, collection, org=org, source="upload", document_type="pdf")
    await _insert(store, collection, org=org, source="s3", document_type="pdf")
    await _insert(store, collection, org=org, source="upload", document_type="docx")

    # source AND document_type both applied.
    got = await _ids(store, collection, _tenant(org, source=["upload"], document_type=["pdf"]))
    assert got == {pdf_upload}


async def test_or_within_a_multi_value_field(engine: AsyncEngine) -> None:
    collection = f"orwithin_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org = uuid.uuid4()
    a = await _insert(store, collection, org=org, source="upload")
    b = await _insert(store, collection, org=org, source="s3")
    await _insert(store, collection, org=org, source="gdrive")

    got = await _ids(store, collection, _tenant(org, source=["upload", "s3"]))
    assert got == {a, b}


async def test_a_date_range_is_inclusive_and_excludes_missing_dates(engine: AsyncEngine) -> None:
    collection = f"dated_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org = uuid.uuid4()
    jan = await _insert(store, collection, org=org, doc_date="2025-01-15")
    await _insert(store, collection, org=org, doc_date="2025-03-01")
    await _insert(store, collection, org=org, doc_date=None)  # a chunk with no date

    got = await _ids(
        store,
        collection,
        _tenant(org, date_from="2025-01-01", date_to="2025-02-01"),
    )
    assert got == {jan}


async def test_an_impossible_date_is_excluded_and_never_raises(engine: AsyncEngine) -> None:
    collection = f"baddate_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org = uuid.uuid4()
    good = await _insert(store, collection, org=org, doc_date="2025-05-01")
    await _insert(store, collection, org=org, doc_date="2025-99-99")

    # The search returns (does not 500) and the impossible-dated row fails closed.
    got = await _ids(store, collection, _tenant(org, date_from="2025-01-01"))
    assert got == {good}


async def test_the_facet_returns_present_values_and_omits_absent_ones(engine: AsyncEngine) -> None:
    collection = f"facet_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    org, other = uuid.uuid4(), uuid.uuid4()
    await _insert(store, collection, org=org, organizational_unit="legal")
    await _insert(store, collection, org=org, organizational_unit="sales")
    # Another tenant's value must not leak into the facet.
    await _insert(store, collection, org=other, organizational_unit="engineering")

    values = await store.distinct_metadata_values(
        collection, ["organizational_unit"], TenantScope(organization_id=org)
    )
    assert values["organizational_unit"] == ["legal", "sales"]


async def test_the_facet_rejects_a_non_whitelisted_key(engine: AsyncEngine) -> None:
    store = _store(engine)
    with pytest.raises(ValueError, match="facetable"):
        await store.distinct_metadata_values(
            "anything", ["content"], TenantScope(organization_id=uuid.uuid4())
        )


def _vec(rng: random.Random) -> list[float]:
    return [round(rng.uniform(-1, 1), 4) for _ in range(_DIM)]


async def _raw_insert(
    store: PgVectorStore, collection: str, *, org: uuid.UUID, vector: list[float]
) -> str:
    """Insert one chunk with a chosen embedding, bypassing the stub embedder.

    The recall test needs distinct, spread-out vectors so the tenant filter is a
    genuine filtered ANN scan rather than a set of identical points.
    """
    import json

    doc_id = str(uuid.uuid4())
    async with store.async_session() as session:
        await session.execute(
            text(
                f"INSERT INTO rag_{collection} (id, parent_doc_id, content, embedding, metadata) "  # noqa: S608
                "VALUES (:id, :pid, :content, :emb, :meta)"
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": doc_id,
                "content": "chunk",
                "emb": str(vector),
                "meta": json.dumps({"organization_id": str(org)}),
            },
        )
        await session.commit()
    return doc_id


async def test_a_selective_tenant_filter_still_returns_a_full_in_scope_top_k(
    engine: AsyncEngine,
) -> None:
    """FA-039 H1: the mandatory tenant conjunct is selective on a shared table, so
    a plain HNSW scan could return fewer than k in-scope rows even when more exist.
    With the store's iterative-scan tuning, a small-tenant filter must still fill k.

    The search is forced onto the HNSW index - seq scan AND the org bitmap-index
    prefilter both disabled, confirmed by EXPLAIN - so neither a seq scan nor an
    exact index prefilter (both recall-safe by construction, but not the ANN path
    H1 is about) can make the assertion vacuous. Disabling the bitmap prefilter is
    also the honest note that, in practice, the org hash index the store builds
    lets the planner answer a selective tenant filter exactly, without the HNSW
    recall risk at all - the iterative-scan tuning is the belt-and-braces for when
    it cannot.
    """
    collection = f"recall_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    await store._ensure_collection(collection)  # the table plus its HNSW index

    # The recall guarantee is delivered by iterative index scan, which needs
    # pgvector >= 0.8 (design P2). On an older image the store falls back to a
    # raised ef_search that does not claim the same recall, so this specific
    # guarantee is not assertable there - skip rather than fail a supported build.
    async with store.async_session() as session:
        extversion = (
            await session.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar()
    if extversion is None or tuple(int(p) for p in extversion.split(".")[:2]) < (0, 8):
        pytest.skip(f"iterative index scan needs pgvector >= 0.8 (found {extversion})")

    rng = random.Random(1593)
    mine, noise = uuid.uuid4(), uuid.uuid4()
    in_scope: set[str] = set()
    for _ in range(25):
        in_scope.add(await _raw_insert(store, collection, org=mine, vector=_vec(rng)))
    for _ in range(1000):
        await _raw_insert(store, collection, org=noise, vector=_vec(rng))

    # `enable_sort = off` matters as much as the scan disables: with a hash index on
    # the org key, the planner can answer the filter with an ordered index scan on it
    # plus a Sort by distance - a plan the seq/bitmap disables do not touch. Taking
    # Sort away leaves the HNSW index, which returns rows in distance order for free.
    force_hnsw = (
        "SET LOCAL enable_seqscan = off",
        "SET LOCAL enable_bitmapscan = off",
        "SET LOCAL enable_sort = off",
    )

    async with store.async_session() as session:
        for stmt in force_hnsw:
            await session.execute(text(stmt))
        plan = await session.execute(
            text(
                f"EXPLAIN SELECT 1 FROM rag_{collection} "  # noqa: S608
                "WHERE metadata->>'organization_id' = :org "
                "ORDER BY embedding <=> :q LIMIT 10"
            ),
            {"org": str(mine), "q": str(_vec(rng))},
        )
        plan_text = "\n".join(row[0] for row in plan.fetchall())
    if "embedding_idx" not in plan_text:
        # Even with seq/bitmap/sort disabled a planner may still answer a selective
        # tenant filter exactly (an ordered scan over the in-scope rows), which is
        # recall-safe by construction. The ANN recall guarantee is only assertable on
        # the HNSW path, so skip - do not fail - when the planner does not take it.
        pytest.skip(f"planner did not take the HNSW path:\n{plan_text}")

    # Force the search onto that index too, so full recall is a property of the
    # iterative scan and not of a plan that trivially sees every in-scope row.
    async def _forced(session) -> None:
        for stmt in force_hnsw:
            await session.execute(text(stmt))
        await PgVectorStore._apply_search_tuning(store, session)

    store._apply_search_tuning = _forced  # type: ignore[method-assign]

    results = await store.search(
        collection, "anything", RetrievalQuery(scope=TenantScope(organization_id=mine)), limit=10
    )
    assert len(results) == 10
    assert all(r.parent_doc_id in in_scope for r in results)
