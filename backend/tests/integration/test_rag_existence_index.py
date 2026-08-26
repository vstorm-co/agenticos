"""The existence check, asked of a real Postgres and its indexes (#1102).

`IngestionService.existing_document` used to read every row of the runtime
`rag_<collection>` table to answer "does this collection already hold this
file". `PgVectorStore.find_existing_document` now looks the document up by an
indexed `metadata->>` key instead - which only a real database, carrying the
expression indexes `_ensure_collection` builds, actually exercises.

The precedence and the #548 single-document invariant are pinned by name in the
unit suite (`tests/test_rag_document_lookup.py`); what is here is that the
indexes exist and that the indexed SQL agrees with that precedence on real rows,
including the two orderings a heap would decide wrong.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.vector_tables import (
    VECTOR_CONTENT_HASH_INDEX_SUFFIX,
    VECTOR_FILENAME_INDEX_SUFFIX,
    VECTOR_SOURCE_PATH_INDEX_SUFFIX,
)
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"


async def _no_resolution(
    _name: str, _organization_id: object = None, _kb_id: object = None
) -> None:
    """A resolver that defers to the store's default embedder and width.

    `_ensure_collection` reads only the width to build the table; the embedder
    it returns is never touched on the DDL path.
    """
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.embedder = None  # type: ignore[assignment]  # unread for DDL, see _no_resolution
    store._resolver = _no_resolution  # type: ignore[assignment]
    return store


async def _insert(
    store: PgVectorStore,
    *,
    doc_id: str,
    source_path: str,
    filename: str,
    content_hash: str,
) -> None:
    meta = json.dumps(
        {"source_path": source_path, "filename": filename, "content_hash": content_hash}
    )
    # TABLE is a module constant and every value is bound - the interpolation S608
    # flags is the table name, which no test controls.
    insert = (
        f"INSERT INTO {TABLE} (id, parent_doc_id, content, metadata) "  # noqa: S608
        "VALUES (:id, :pid, :content, CAST(:meta AS jsonb))"
    )
    async with store.async_session() as session:
        await session.execute(
            text(insert),
            {"id": f"{doc_id}-0", "pid": doc_id, "content": "body", "meta": meta},
        )
        await session.commit()


@pytest.fixture(autouse=True)
async def _clean_runtime_table(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """The runtime table is not a model, so nothing else drops it between tests."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def test_ensure_collection_builds_an_index_per_lookup_key(engine: AsyncEngine) -> None:
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)

    async with store.async_session() as session:
        result = await session.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :t"), {"t": TABLE}
        )
        defs = {row[0]: row[1] for row in result.all()}

    # Hash, not btree: a btree on an unbounded `source_path` fails the index-row
    # -size limit and takes ingestion down with it (#1102 review).
    for suffix in (
        VECTOR_SOURCE_PATH_INDEX_SUFFIX,
        VECTOR_FILENAME_INDEX_SUFFIX,
        VECTOR_CONTENT_HASH_INDEX_SUFFIX,
    ):
        name = f"{TABLE}{suffix}"
        assert name in defs
        assert "USING hash" in defs[name]


async def test_source_path_wins_and_returns_that_documents_own_hash(engine: AsyncEngine) -> None:
    """#548: the id and the hash name one document.

    `decoy` shares the filename and is *unaddressed* (its source_path is its own
    name), so a by-filename read would take it - and it sorts before `live` by
    `parent_doc_id`, so a heap-ordered scan would too. The source_path match must
    still win and hand back `live`'s own hash, not `decoy`'s.
    """
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    await _insert(
        store,
        doc_id="decoy",
        source_path="handbook.pdf",
        filename="handbook.pdf",
        content_hash="v2",
    )
    await _insert(
        store,
        doc_id="live",
        source_path="/srv/sync/handbook.pdf",
        filename="handbook.pdf",
        content_hash="v1",
    )

    hit = await store.find_existing_document(
        COLLECTION, source_path="/srv/sync/handbook.pdf", content_hash="unrelated"
    )

    assert hit is not None
    assert hit.document_id == "live"
    assert (hit.additional_info or {}).get("content_hash") == "v1"


async def test_the_filename_fallback_keeps_the_unaddressed_rule(engine: AsyncEngine) -> None:
    """#990: a source_path miss matches a same-name document only where that
    document has not addressed itself under a different path."""
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    await _insert(
        store,
        doc_id="addressed",
        source_path="/srv/a/handbook.pdf",
        filename="handbook.pdf",
        content_hash="v1",
    )
    await _insert(
        store,
        doc_id="unaddressed",
        source_path="handbook.pdf",
        filename="handbook.pdf",
        content_hash="v2",
    )

    hit = await store.find_existing_document(
        COLLECTION, source_path="/elsewhere/handbook.pdf", content_hash=""
    )

    assert hit is not None
    assert hit.document_id == "unaddressed"


async def test_content_hash_is_the_last_resort(engine: AsyncEngine) -> None:
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    await _insert(
        store, doc_id="moved", source_path="/old/name.pdf", filename="name.pdf", content_hash="same"
    )

    hit = await store.find_existing_document(
        COLLECTION, source_path="/new/renamed.pdf", content_hash="same"
    )

    assert hit is not None
    assert hit.document_id == "moved"


async def test_the_fallback_tiebreak_is_deterministic(engine: AsyncEngine) -> None:
    """#548's other half: when several rows match one fallback branch, the row
    chosen is fixed by `ORDER BY parent_doc_id, id`, not by heap order. Two
    unaddressed documents share a filename; the lower `parent_doc_id` wins."""
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    await _insert(
        store, doc_id="bbb", source_path="dup.pdf", filename="dup.pdf", content_hash="v-b"
    )
    await _insert(
        store, doc_id="aaa", source_path="dup.pdf", filename="dup.pdf", content_hash="v-a"
    )

    hit = await store.find_existing_document(
        COLLECTION, source_path="/nowhere/dup.pdf", content_hash=""
    )

    assert hit is not None
    assert hit.document_id == "aaa"


async def test_a_source_path_too_long_for_a_btree_index_still_ingests(engine: AsyncEngine) -> None:
    """#1102 review: a btree metadata index caps entries near 2700 bytes, so a
    long path would fail every ingest into the collection. The hash index has no
    such ceiling - this row inserts and is found."""
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    long_path = "s3://bucket/" + "a" * 3000
    await _insert(store, doc_id="big", source_path=long_path, filename="big.pdf", content_hash="h")

    hit = await store.find_existing_document(COLLECTION, source_path=long_path, content_hash="")

    assert hit is not None
    assert hit.document_id == "big"


async def test_no_key_matches_answers_none(engine: AsyncEngine) -> None:
    store = _store(engine)
    await store._ensure_collection(COLLECTION, None)
    await _insert(
        store, doc_id="only", source_path="/srv/other.pdf", filename="other.pdf", content_hash="h"
    )

    hit = await store.find_existing_document(
        COLLECTION, source_path="/srv/absent.pdf", content_hash="nope"
    )

    assert hit is None
