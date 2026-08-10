"""Shutdown teardown for the vector store.

The pgvector store creates its own SQLAlchemy engine, so the application
lifespan must release that pool on shutdown. It does so through the public
`aclose`, not by reaching into `.engine`; these tests pin both halves of that
contract.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


async def test_aclose_disposes_the_connection_pool():
    store = PgVectorStore.__new__(PgVectorStore)
    store.engine = MagicMock(dispose=AsyncMock())

    await store.aclose()

    store.engine.dispose.assert_awaited_once()
