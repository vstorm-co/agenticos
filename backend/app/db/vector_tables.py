"""The tables the vector store creates at runtime, and telling them from schema.

`PgVectorStore` issues `CREATE TABLE IF NOT EXISTS rag_<collection>` the first time
a collection is written to, so those tables exist in the database and in nothing
else - no model declares them and no migration creates them. That is correct: they
are per-collection runtime objects, and a deployment holds as many as somebody has
made knowledge bases.

It is also invisible to `alembic check`, which compares the whole database against
the models and reads every one of them as a table the models dropped. The result is
inverted: a gate meant to catch "edited a model, forgot the migration" failed for a
reason that has nothing to do with models, on exactly the machines where somebody is
editing them (#288).

The prefix lives here rather than in `vectorstore.py` because two places need it and
they answer to different layers: the store builds a name, `alembic/env.py` has to
recognise one. Sharing a string is the easy half. The hard half is
`is_runtime_vector_table` below, because **`rag_documents` is a real model table** -
so "starts with `rag_`" is not a safe test, and an exclusion that got it wrong would
silence real drift in the one table this project ingests through.

Both sides of that ask it now. `alembic/env.py` asks which tables it must not
compare; `PgVectorStore.list_collections` asks which are collections, and until it
did, the prefix alone had it reporting `rag_documents` as a collection called
`documents` (#339). One question, one answer, whichever direction it is read from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import MetaData

VECTOR_TABLE_PREFIX = "rag_"


def is_runtime_vector_table(name: str, *, metadata: MetaData) -> bool:
    """Whether this table belongs to the vector store rather than to alembic.

    Both halves are load-bearing. The prefix alone would exclude `rag_documents`,
    which the models declare and alembic owns; membership in `metadata` alone would
    exclude every table any extension or another application put in the database.
    Together they mean one thing only: a `rag_` table the models have never heard
    of, which is exactly what the store creates.

    Args:
        name: A table name as reflected from the database.
        metadata: The metadata to judge against - what autogenerate is comparing to,
            or `Base.metadata` for a caller outside alembic. A parameter rather
            than an import because this function must not choose: whichever
            metadata the caller is reasoning about is the one the answer has to
            be true of. It does not make the answer independent of what has been
            imported - a caller passing `Base.metadata` is asserting that the
            models are registered on it, and one that has not imported them gets
            "every `rag_` table is the store's" with no error to say so.

    Example:
        ```python
        is_runtime_vector_table("rag_company_handbook", metadata=Base.metadata)  # True
        is_runtime_vector_table("rag_documents", metadata=Base.metadata)  # False
        ```
    """
    return name.startswith(VECTOR_TABLE_PREFIX) and name not in metadata.tables
