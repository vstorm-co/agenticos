"""What the vector store lists, asked of a real database.

The unit version of this (`tests/test_collection_listing.py`) hands the store a
fixed list of table names, which proves the predicate is applied but takes on
trust the two facts the bug actually rested on: that `rag_documents` is really
there, and that the store's own query really returns it. Both come from the
database or not at all - the first from `Base.metadata.create_all`, the second
from `information_schema` - so they are asked here (#339).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


async def test_the_listing_holds_the_collection_and_not_the_documents_table(
    engine: AsyncEngine,
) -> None:
    """A database with both in it answers with the collection alone.

    The collection's table is created with raw DDL rather than through
    `create_collection`: that path needs the `vector` extension, an embedding
    width and a resolver, none of which this is about. What `list_collections`
    reads is a name in `information_schema`, and this is one.
    """
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE rag_company_handbook (id VARCHAR(100))"))
        present = await connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name LIKE 'rag_%' AND table_schema = 'public'"
            )
        )
        # The premise, asserted rather than assumed: the tracking table is in
        # this database and does carry the prefix the store matches on. Derived
        # from the metadata, so a second prefixed model table added later is part
        # of the premise instead of failing this line.
        modelled = {name for name in Base.metadata.tables if name.startswith(VECTOR_TABLE_PREFIX)}
        assert "rag_documents" in modelled
        assert {row[0] for row in present} == modelled | {"rag_company_handbook"}

    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)

    assert await store.list_collections() == ["company_handbook"]
