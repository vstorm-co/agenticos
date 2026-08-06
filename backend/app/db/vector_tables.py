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

Three sides of that ask it now. `alembic/env.py` asks which tables it must not
compare; `PgVectorStore.list_collections` asks which are collections, and until it
did, the prefix alone had it reporting `rag_documents` as a collection called
`documents` (#339); and `collides_with_model_table` asks it of a name nobody has
created yet, which is the only moment a collection called `documents` can still be
refused rather than aimed at the tracking table (#345). One question, one answer,
whichever direction it is read from.
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


def collides_with_model_table(collection: str, *, metadata: MetaData) -> bool:
    """Whether a collection by this name would land on a table the models own.

    The store names a collection's table by prefixing it, so `documents` lands on
    `rag_documents` - the table tracking every ingested document in the
    deployment, for every organization in it. Nothing about that is visible from
    the name a caller typed, and the consequence is not a confused read:
    `delete_collection` issues `DROP TABLE IF EXISTS`, so one tenant tidying up
    their own collection aims it at everybody's tracking (#345).

    This is the same question :func:`is_runtime_vector_table` answers, asked
    before the table exists, so it is that function inverted rather than a list of
    reserved names kept alongside it. The reserved set is therefore whatever the
    models declare: a second `rag_`-prefixed model table added tomorrow is refused
    without anybody remembering this function is here.

    Args:
        collection: A collection name as a caller supplied it.
        metadata: The metadata to judge against, normally `Base.metadata` - with
            the same caveat :func:`is_runtime_vector_table` carries. A caller that
            has not imported the models is asserting an empty metadata, and gets
            "nothing collides" with no error to say so.

    Note:
        The name is folded first because the store interpolates it into DDL
        unquoted and Postgres folds an unquoted identifier: `Documents` reaches
        the same table `documents` does, so a check comparing the name as typed
        would refuse one spelling and hand the other a `DROP`.

    Example:
        ```python
        collides_with_model_table("documents", metadata=Base.metadata)  # True
        collides_with_model_table("documents_archive", metadata=Base.metadata)  # False
        ```
    """
    return not is_runtime_vector_table(
        f"{VECTOR_TABLE_PREFIX}{collection.lower()}", metadata=metadata
    )
