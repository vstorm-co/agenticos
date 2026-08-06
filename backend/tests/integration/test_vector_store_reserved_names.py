"""What the store does to a real `rag_documents`, and to a name beside it.

The unit version (`tests/test_reserved_collection_names.py`) asserts that no
statement is issued, which is the fix. What it cannot assert is the premise the
bug rested on: that the name the store builds is a table that is really there,
holding rows belonging to organizations the caller has never heard of. That
comes from the database or not at all (#345).

The second test is the other half, and the reason the refusal is derived from
`Base.metadata` rather than from the name: a collection called
`documents_archive` still has to be created and dropped for real, against
pgvector, index and all.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.exceptions import BadRequestError
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

_A_TRACKED_DOCUMENT = text(
    "INSERT INTO rag_documents "
    "(id, collection_name, filename, filesize, filetype, status, chunk_count) "
    "VALUES (gen_random_uuid(), :collection, 'handbook.pdf', 12, 'pdf', 'indexed', 3)"
)


def _store_on(engine: AsyncEngine) -> PgVectorStore:
    """A store over this engine, with no resolver and a narrow vector width.

    `__new__` rather than the constructor: that one builds an engine of its own
    from the deployment settings, which is the database this test is deliberately
    not using. The width is small because nothing here embeds anything - it only
    has to be a width pgvector will build an index at.
    """
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store._resolver = None
    store.embedder = None  # ty: ignore[invalid-assignment] - unused without a resolver
    store.dim = 8
    return store


async def test_dropping_a_collection_cannot_reach_the_tracking_table(
    engine: AsyncEngine,
) -> None:
    """The row survives, and it belongs to somebody who never made the call.

    A caller who names their collection `documents` is asking to drop
    `rag_documents`, and what is in it is every organization's ingestion
    history - here, a row for a collection with an unrelated name.
    """
    async with engine.begin() as connection:
        await connection.execute(_A_TRACKED_DOCUMENT, {"collection": "another_orgs_handbook"})

    with pytest.raises(BadRequestError) as refused:
        await _store_on(engine).delete_collection("documents")

    assert refused.value.details == {"collection": "documents", "table": "rag_documents"}
    async with engine.connect() as connection:
        surviving = await connection.execute(text("SELECT collection_name FROM rag_documents"))
        assert [row[0] for row in surviving] == ["another_orgs_handbook"]


async def test_a_collection_beside_it_is_created_and_dropped_for_real(
    engine: AsyncEngine,
) -> None:
    """`documents_archive` is a name a too-broad refusal would have taken.

    Run against pgvector rather than mocked: `create_collection` needs the
    extension and builds an HNSW index, which is the step that fails when a
    name lands on a table that has no `embedding` column - the loud half of
    #345, and the reason this case is worth proving end to end.
    """
    store = _store_on(engine)

    await store.create_collection("documents_archive")

    async with engine.connect() as connection:
        created = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = 'rag_documents_archive' AND table_schema = 'public'"
            )
        )
        assert created.scalar() == "rag_documents_archive"

    await store.delete_collection("documents_archive")

    async with engine.connect() as connection:
        remaining = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'rag_documents%' AND table_schema = 'public'"
            )
        )
        assert [row[0] for row in remaining] == ["rag_documents"]
