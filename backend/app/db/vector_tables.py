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

Collisions with a model table are one of four ways a caller-supplied name can land
somewhere it should not, and :func:`validate_collection_name` is all four in one
place. They belong together because they are one question - is this string safe to
build an identifier out of - and because they were four places: a regex in the
store's `create_collection`, a laxer one in its `_table`, a reserved set beside the
first, and the model-table check here. The two regexes disagreed, and every read,
write and drop went through the lax one (#368, #371).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.exceptions import BadRequestError

if TYPE_CHECKING:
    from sqlalchemy import MetaData

VECTOR_TABLE_PREFIX = "rag_"

VECTOR_INDEX_SUFFIX = "_embedding_idx"
"""What the store appends to a table name for its HNSW index.

Here rather than in `vectorstore.py` for the reason the prefix is: the store
builds the identifier and :data:`MAX_COLLECTION_NAME_LENGTH` is derived from its
length, so a rename in one place without the other silently re-opens the
truncation below.
"""

_MAX_IDENTIFIER_LENGTH = 63
"""What Postgres keeps of an identifier - `NAMEDATALEN - 1`, in bytes.

Bytes, not characters, but :data:`_COLLECTION_NAME_RE` admits ASCII only, so for
a name that got this far the two are the same number.
"""

MAX_COLLECTION_NAME_LENGTH = (
    _MAX_IDENTIFIER_LENGTH - len(VECTOR_TABLE_PREFIX) - len(VECTOR_INDEX_SUFFIX)
)
"""The longest collection name every identifier built from it survives.

The index name is the binding constraint, not the table name: `rag_<name>` fits
at 59 characters but `rag_<name>_embedding_idx` does not, and Postgres truncates
rather than refusing. Two collections agreeing to the truncation point are then
one object - one table if the name was too long, and one index if only the index
name was, which is the quieter half: `CREATE INDEX IF NOT EXISTS` finds the first
collection's index already there and builds nothing, so the second searches
unindexed at whatever width the first was built at (#368).
"""

_COLLECTION_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
"""A name the store can interpolate into DDL unquoted, which is how it does it.

Leading letter included: an identifier starting with a digit has to be quoted,
and `rag_2024_reports` only looks safe because the prefix supplies the letter.
The store's two regexes disagreed on exactly this, and the one that admitted it
was the one on every path.
"""

_RESERVED_COLLECTION_NAMES = frozenset({"all"})
"""Names that mean something other than a collection, and so cannot be one."""


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


def validate_collection_name(collection: str, *, metadata: MetaData) -> None:
    """Refuse a collection name that cannot safely become an identifier.

    Every path that accepts a name a caller chose asks this, and there is
    nothing else to ask: the store asks it in `_table`, so the CLI and the
    ingestion worker are covered without a route, and
    :meth:`app.services.collection_access.CollectionAccessService.claim` asks it
    before the question only it can answer - whether the name is already another
    organization's.

    The four refusals, in the order a name meets them:

    * **Shape.** Anything the store could not interpolate into DDL unquoted.
    * **Length.** See :data:`MAX_COLLECTION_NAME_LENGTH`; Postgres truncates
      silently, so this is the difference between two collections and one.
    * **Reserved.** :data:`_RESERVED_COLLECTION_NAMES`.
    * **A table the models own.** :func:`collides_with_model_table`.

    All four raise `BadRequestError` rather than `ValueError`. Two of them used
    to raise `ValueError`, which no handler maps, so a name the server
    understood perfectly and declined arrived as `500 INTERNAL_ERROR` with its
    message replaced by "An unexpected error occurred" (#371).

    Args:
        collection: A collection name as a caller supplied it.
        metadata: The metadata to judge the collision against, with the caveat
            :func:`collides_with_model_table` carries.

    Raises:
        BadRequestError: On any of the four, naming the rule that refused it.
    """
    if not _COLLECTION_NAME_RE.match(collection):
        raise BadRequestError(
            message=(
                "A collection name must start with a letter and hold only "
                "letters, numbers and underscores"
            ),
            details={"collection": collection},
        )
    if len(collection) > MAX_COLLECTION_NAME_LENGTH:
        raise BadRequestError(
            message=(
                f"A collection name may be at most {MAX_COLLECTION_NAME_LENGTH} "
                "characters, or the table and index built from it are truncated "
                "onto another collection's"
            ),
            details={"collection": collection, "max_length": MAX_COLLECTION_NAME_LENGTH},
        )
    if collection.lower() in _RESERVED_COLLECTION_NAMES:
        raise BadRequestError(
            message=f"'{collection}' is a reserved collection name",
            details={"collection": collection},
        )
    if collides_with_model_table(collection, metadata=metadata):
        raise BadRequestError(
            message=f"'{collection}' is a reserved collection name",
            details={
                "collection": collection,
                "table": f"{VECTOR_TABLE_PREFIX}{collection.lower()}",
            },
        )
