"""What `alembic check` is allowed to ignore, and what it must never ignore.

`make db-check` is the gate that catches "edited a model, forgot the migration". It
failed instead on any database that had ever ingested a document, because the vector
store creates a `rag_<collection>` table per collection at runtime and autogenerate
read each one as a table the models had dropped (#288). So the comparison now skips
them - and an exclusion inside a drift gate is a way to silence drift, which is why
the predicate is tested here rather than trusted.

The test that matters most is the parametrised one: **no table the models declare may
ever be excluded.** `rag_documents` is a real model table, so the obvious version of
this fix - skip anything starting with `rag_` - would have turned the gate off for the
one table this project ingests through, and nothing would have said so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.db.models  # noqa: F401  - registers every table on the metadata
from app.db.base import Base
from app.db.vector_tables import VECTOR_TABLE_PREFIX, is_runtime_vector_table

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def test_a_collections_runtime_table_is_not_alembics() -> None:
    """Built from the shared prefix, which is what the store builds its names with."""
    table = f"{VECTOR_TABLE_PREFIX}company_handbook_12db7e"

    assert is_runtime_vector_table(table, metadata=Base.metadata)


def test_the_documents_table_is_alembics() -> None:
    """It starts with the prefix and is a model table, which is the whole trap."""
    assert "rag_documents" in Base.metadata.tables
    assert not is_runtime_vector_table("rag_documents", metadata=Base.metadata)


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_no_table_the_models_declare_is_ever_excluded(table: str) -> None:
    """Parametrised over the metadata, so a table added later is covered by this code.

    An exclusion that grows to cover a modelled table is a gate that stops reporting a
    missing migration - green, and wrong in the direction nobody checks.
    """
    assert not is_runtime_vector_table(table, metadata=Base.metadata)


def test_a_table_without_the_prefix_is_left_alone() -> None:
    """Not being in the metadata is not on its own a reason to skip anything.

    An extension's table, or another application sharing the database, has to keep
    reading as unknown: that is a conversation with whoever put it there, not
    something this predicate should quietly absorb.
    """
    assert not is_runtime_vector_table("spatial_ref_sys", metadata=Base.metadata)


def test_the_store_names_its_tables_from_the_shared_prefix() -> None:
    """Two literals would drift, and the drift is silent in the worst way.

    Names built from a second literal keep working - the store creates and reads its
    own tables - while `alembic check` stops recognising them and `db-check` starts
    failing again on exactly the machines #288 was about.
    """
    source = (BACKEND_ROOT / "app" / "services" / "rag" / "vectorstore.py").read_text()

    assert "VECTOR_TABLE_PREFIX" in source
    assert '"rag_' not in source and "'rag_" not in source, (
        "the vector store spells the prefix out again; import VECTOR_TABLE_PREFIX from "
        "app/db/vector_tables.py instead, which is what alembic/env.py recognises"
    )
