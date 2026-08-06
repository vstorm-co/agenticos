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

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import app.db.models  # noqa: F401  - registers every table on the metadata
from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

BACKEND_ROOT = Path(__file__).resolve().parent.parent


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


def test_the_store_registers_the_models_it_judges_a_table_against() -> None:
    """The one line holding the fix up, and the only way left to guard it.

    `is_runtime_vector_table` is only as good as the metadata handed to it: on an
    empty `Base.metadata` every prefixed table reads as a collection, which is
    #339 again with no error to announce it. So `vectorstore.py` imports
    `app.db.models` for the side effect.

    That import is *currently* redundant - `app.services.embedding_resolution`
    reaches the models through `app.repositories` - and redundant is exactly the
    problem. It makes the line read as unused (it carries a `noqa`, so nothing
    else objects), and it puts the correctness of this listing on an import chain
    belonging to a different concern, which a refactor may cut without ever
    looking here.

    Asserted on the source because no run of this suite can assert it on
    behaviour: `tests/conftest.py` imports `app.main`, so the metadata is
    populated before any test module loads, and even a subprocess would still be
    saved by the accidental route - a test that cannot fail on the edit worth
    catching is not a guard.
    """
    source = (BACKEND_ROOT / "app" / "services" / "rag" / "vectorstore.py").read_text()

    assert "import app.db.models" in source, (
        "the vector store no longer registers the models on Base.metadata, so "
        "list_collections judges tables against whatever happens to have been imported; "
        "on an empty metadata it reports rag_documents as a collection again (#339)"
    )


async def test_a_collection_whose_name_starts_like_a_model_table_still_lists() -> None:
    """`documents_archive` is a collection somebody may reasonably create.

    Excluding the literal `documents`, or anything beginning with it, would answer
    #339 for the phantom and hide a real collection alongside it. The store asks
    whether the models declare *that table*, which is a question about the database
    rather than about how a name reads.
    """
    store = _store_over([f"{VECTOR_TABLE_PREFIX}documents_archive"])

    assert await store.list_collections() == ["documents_archive"]
