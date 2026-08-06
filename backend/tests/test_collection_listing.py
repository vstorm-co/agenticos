"""What the vector store says it holds.

`list_collections` is the store's own answer to "which collections exist" - what a
`rag-collections` command prints, and what an existence check reads. It selected
every table carrying the store's prefix, and `rag_documents` carries it without
being a collection: it is the model table tracking ingested documents. So the
listing held a phantom called `documents` on every deployment since that table
existed, and a caller that believed it would read chunks out of a table with none
of the columns it expects (#339).

The fix is the predicate `alembic/env.py` already asks from the other side, not a
name this file could spell out - which is why the second test below exists. A
collection genuinely called `documents_archive` has to keep listing.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import app.db.models  # noqa: F401  - registers every table on the metadata
from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio


class _Result:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[str]]:
        return self._rows


class _Session:
    """The one query `list_collections` makes, answered from a fixed table list."""

    def __init__(self, table_names: list[str]) -> None:
        self._rows = [(name,) for name in table_names]

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    async def execute(self, statement: Any, parameters: Any = None) -> _Result:
        return _Result(self._rows)


def _store_over(table_names: list[str]) -> PgVectorStore:
    """A store whose database holds exactly these tables and no engine at all."""
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = MagicMock(return_value=_Session(table_names))
    return store


def _modelled_prefixed_tables() -> list[str]:
    return sorted(name for name in Base.metadata.tables if name.startswith(VECTOR_TABLE_PREFIX))


async def test_a_table_the_models_own_is_not_reported_as_a_collection() -> None:
    """The regression. Built from the metadata, so a later one is covered too.

    `rag_documents` is the one that made this a bug, and the assertion below keeps
    the case from quietly emptying if the model is ever renamed - but the row list
    is every prefixed table the models declare, so a second one added tomorrow is
    tested by this code rather than by somebody remembering.
    """
    modelled = _modelled_prefixed_tables()
    assert "rag_documents" in modelled

    store = _store_over([*modelled, f"{VECTOR_TABLE_PREFIX}company_handbook"])

    assert await store.list_collections() == ["company_handbook"]


async def test_a_collection_whose_name_starts_like_a_model_table_still_lists() -> None:
    """`documents_archive` is a collection somebody may reasonably create.

    Excluding the literal `documents`, or anything beginning with it, would answer
    #339 for the phantom and hide a real collection alongside it. The store asks
    whether the models declare *that table*, which is a question about the database
    rather than about how a name reads.
    """
    store = _store_over([f"{VECTOR_TABLE_PREFIX}documents_archive"])

    assert await store.list_collections() == ["documents_archive"]
