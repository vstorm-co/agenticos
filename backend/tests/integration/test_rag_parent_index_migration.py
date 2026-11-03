"""0252 builds the `parent_doc_id` index on the runtime vector tables that predate it (#2552).

`delete_document`, `get_document_chunks` and `get_chunks_around` filter a
`rag_<collection>` table by `parent_doc_id`. `_ensure_collection` now indexes the
column, but only when it runs, so a collection nobody writes to again would keep
scanning its scope on every delete and parent-context expansion. The migration
builds the same index on every existing runtime table.

Driven against a real database because the migration discovers tables no model
declares and asks `pg_index` whether an index of that name is valid.
"""

import importlib.util
from collections.abc import AsyncGenerator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.vector_tables import VECTOR_PARENT_INDEX_SUFFIX
from app.services.rag.vectorstore import PgVectorStore

pytestmark = pytest.mark.anyio

COLLECTION = "handbook"
TABLE = f"rag_{COLLECTION}"
INDEX = f"{TABLE}{VECTOR_PARENT_INDEX_SUFFIX}"


def _load_migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0252_index_rag_parent_doc_id.py"
    )
    spec = importlib.util.spec_from_file_location("mig_0252_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_url(schema_url: str) -> str:
    return schema_url.replace("+asyncpg", "+psycopg2")


def _run(schema_url: str, direction: str) -> None:
    migration = _load_migration()
    sync_engine = create_engine(_sync_url(schema_url))
    try:
        with sync_engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                (migration.upgrade if direction == "up" else migration.downgrade)()
    finally:
        sync_engine.dispose()


async def _no_resolution(_name: str, _organization_id: object = None) -> None:
    return


def _store(engine: AsyncEngine) -> PgVectorStore:
    store = PgVectorStore.__new__(PgVectorStore)
    store.async_session = async_sessionmaker(engine, expire_on_commit=False)
    store.dim = 3
    store.embedder = None  # type: ignore[assignment]  # unread on the DDL path
    store._resolver = _no_resolution  # type: ignore[assignment]
    return store


async def _parent_indexes(engine: AsyncEngine) -> list[tuple[str, bool, str]]:
    """Every index on the runtime table that covers `parent_doc_id`: name,
    validity and definition."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT c.relname, i.indisvalid, pg_get_indexdef(i.indexrelid) "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE i.indrelid = CAST(:t AS regclass) "
                "AND pg_get_indexdef(i.indexrelid) LIKE '%(parent_doc_id)%'"
            ),
            {"t": TABLE},
        )
        return [(row[0], row[1], row[2]) for row in result.all()]


@pytest.fixture
async def legacy_table(engine: AsyncEngine) -> AsyncGenerator[None]:
    """A runtime table as `_ensure_collection` built it before this revision:
    every index but the `parent_doc_id` one."""
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
    await _store(engine)._ensure_collection(COLLECTION)
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP INDEX IF EXISTS {INDEX}"))
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


async def test_upgrade_builds_the_index_on_an_existing_table(
    engine: AsyncEngine, schema_url: str, legacy_table: None
) -> None:
    assert await _parent_indexes(engine) == []

    _run(schema_url, "up")

    [(name, valid, definition)] = await _parent_indexes(engine)
    assert name == INDEX
    assert valid
    assert definition.endswith("USING btree (parent_doc_id)")


async def test_upgrade_is_idempotent(
    engine: AsyncEngine, schema_url: str, legacy_table: None
) -> None:
    """A second run - or a run over a table `_ensure_collection` already
    indexed - builds nothing more."""
    _run(schema_url, "up")
    _run(schema_url, "up")

    assert [name for name, _, _ in await _parent_indexes(engine)] == [INDEX]


async def test_downgrade_drops_it_and_upgrade_rebuilds_it(
    engine: AsyncEngine, schema_url: str, legacy_table: None
) -> None:
    _run(schema_url, "up")
    _run(schema_url, "down")

    assert await _parent_indexes(engine) == []

    _run(schema_url, "up")

    assert [name for name, valid, _ in await _parent_indexes(engine) if valid] == [INDEX]


async def test_an_invalid_index_left_by_a_failed_concurrent_build_is_replaced(
    engine: AsyncEngine, schema_url: str, legacy_table: None
) -> None:
    """The CHANGELOG tells a large deployment to pre-build the index with
    `CREATE INDEX CONCURRENTLY`. One that fails leaves an INVALID index under the
    name, which `IF NOT EXISTS` alone would keep - and the planner never uses."""
    async with engine.begin() as conn:
        for chunk in ("a", "b"):
            await conn.execute(
                text(
                    f"INSERT INTO {TABLE} (id, parent_doc_id, content) "  # noqa: S608
                    "VALUES (:id, 'doc', 'body')"
                ),
                {"id": f"doc-{chunk}"},
            )
    # A unique build over a duplicated key fails part-way, which is the
    # documented way a concurrent build leaves its index behind INVALID.
    autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(
                text(f"CREATE UNIQUE INDEX CONCURRENTLY {INDEX} ON {TABLE} (parent_doc_id)")
            )
    assert [(name, valid) for name, valid, _ in await _parent_indexes(engine)] == [(INDEX, False)]

    _run(schema_url, "up")

    [(name, valid, definition)] = await _parent_indexes(engine)
    assert (name, valid) == (INDEX, True)
    assert definition.endswith("USING btree (parent_doc_id)")


async def test_the_tracking_table_is_left_alone(
    engine: AsyncEngine, schema_url: str, legacy_table: None
) -> None:
    """`rag_documents` is a model table with the prefix and no `metadata` jsonb
    column; the discovery must not reach it."""
    _run(schema_url, "up")

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = 'rag_documents_parent_idx'")
        )
        assert result.scalar() is None
