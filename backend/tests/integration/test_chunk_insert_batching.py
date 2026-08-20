"""A batched chunk insert, against a real pgvector Postgres.

#950. The unit half (`tests/test_chunk_insert_batching.py`) counts statements
against a recording session, which proves the loop batches and nothing else. Two
facts it takes on trust come from the driver or not at all: that SQLAlchemy hands
a list of parameter dictionaries for a `text()` DML statement to asyncpg as one
`executemany` rather than refusing it, and that `ON CONFLICT (id) DO UPDATE`
still behaves per row when it does. Both are asked here.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.services.rag import vectorstore as vectorstore_module
from app.services.rag.models import (
    Document,
    DocumentMetadata,
    DocumentPage,
    DocumentPageChunk,
)
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

_DIM = 3


def _document(*, chunks: int, body: str = "chunk") -> Document:
    document = Document(
        pages=[DocumentPage(page_num=1, content="body")],
        metadata=DocumentMetadata(filename="handbook.pdf", filesize=10, filetype="pdf"),
    )
    # `parent_doc_id` the way the splitter sets it (`documents.py:685`); the
    # model validator only connects pages, not the chunks assigned after it.
    document.chunked_pages = [
        DocumentPageChunk(
            chunk_content=f"{body} {index}",
            chunk_num=index,
            page_num=1,
            content=f"{body} {index}",
            parent_doc_id=document.id,
        )
        for index in range(chunks)
    ]
    return document


def _store(engine: AsyncEngine) -> PgVectorStore:
    """The real store on the suite's engine, with only the embedder stubbed.

    `_ensure_collection` stays real - the table this writes into is the one it
    creates, including the `vector({dim})` column the rows have to satisfy.
    """
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    embedder = MagicMock(
        embed_document=MagicMock(side_effect=lambda doc: [[0.25] * _DIM for _ in doc.chunked_pages])
    )
    store._for_collection = AsyncMock(return_value=(embedder, _DIM))  # ty: ignore[invalid-assignment]
    return store


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        result = await connection.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
        return int(result.scalar_one())


async def test_a_document_spanning_several_batches_writes_every_row(
    engine: AsyncEngine, monkeypatch
) -> None:
    """250 chunks across a batch size of 100 must be 250 rows, not 100 and not 50."""
    monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 100)
    collection = f"batched_{uuid.uuid4().hex[:8]}"
    store = _store(engine)

    await store.insert_document(collection, _document(chunks=250))

    assert await _count(engine, f"rag_{collection}") == 250


async def test_re_inserting_the_same_chunks_updates_rather_than_duplicates(
    engine: AsyncEngine, monkeypatch
) -> None:
    """`ON CONFLICT (id) DO UPDATE` has to hold per row inside an `executemany`,
    which is what makes a re-ingest of an unchanged document idempotent."""
    monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 4)
    collection = f"upserted_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    document = _document(chunks=10)

    await store.insert_document(collection, document)
    for chunk in document.chunked_pages:
        chunk.chunk_content = f"revised {chunk.chunk_num}"
    await store.insert_document(collection, document)

    table = f"rag_{collection}"
    assert await _count(engine, table) == 10
    async with engine.connect() as connection:
        stored = await connection.execute(
            text(f"SELECT content FROM {table} ORDER BY (metadata->>'chunk_num')::int")  # noqa: S608
        )
        assert [row[0] for row in stored] == [f"revised {index}" for index in range(10)]


async def test_the_chunks_are_readable_back_in_document_order(
    engine: AsyncEngine, monkeypatch
) -> None:
    """The store's own reader is the consumer of these rows, so it is what asserts
    the batches did not scramble what the splitter produced."""
    monkeypatch.setattr(vectorstore_module, "_CHUNK_INSERT_BATCH", 3)
    collection = f"ordered_{uuid.uuid4().hex[:8]}"
    store = _store(engine)
    document = _document(chunks=8)
    parent = document.chunked_pages[0].parent_doc_id

    await store.insert_document(collection, document)

    chunks = await store.get_document_chunks(collection, parent)
    assert [chunk.content for chunk in chunks] == [f"chunk {index}" for index in range(8)]
    assert [chunk.chunk_num for chunk in chunks] == list(range(8))
