"""First filed writes serialize DDL, including when its first transaction fails (#2774)."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import Connection, event, text
from sqlalchemy.engine import AdaptedConnection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.vector_tables import VectorScope
from tests.integration.test_deletion_reconciliation import (
    _org,
    _org_collection,
    _parsed,
    _store_embedding_in_3d,
    _user,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("fail_first", [False, True])
async def test_concurrent_first_filed_writes_survive_creation_and_rollback(
    engine: AsyncEngine, fail_first: bool
) -> None:
    collection = f"firstwrite{uuid4().hex[:12]}"
    table = f"rag_{collection}"
    unrelated = f"parallelcollection{uuid4().hex[:12]}"
    label = f"creation_{uuid4().hex}"
    writers = create_async_engine(
        engine.url,
        pool_size=10,
        max_overflow=0,
        connect_args={"server_settings": {"application_name": label}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        owner = _user()
        session.add(owner)
        await session.flush()
        org = await _org(session, owner)
        base = _org_collection(org.id, collection)
        session.add(base)
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await session.commit()
    store = _store_embedding_in_3d(writers)
    created, release = asyncio.Event(), asyncio.Event()

    async def pause(_driver: object) -> None:
        created.set()
        await release.wait()
        if fail_first:
            raise RuntimeError("First DDL transaction rolls back")

    def after_create(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: ExecutionContext,
        _executemany: bool,
    ) -> None:
        if f"CREATE TABLE IF NOT EXISTS {table} " in statement and not created.is_set():
            adapted = connection.connection.dbapi_connection
            assert isinstance(adapted, AdaptedConnection)
            adapted.run_async(pause)

    event.listen(writers.sync_engine, "after_cursor_execute", after_create)
    documents = [_parsed(f"document-{i}") for i in range(4)]
    tasks = [
        asyncio.create_task(store.insert_document(collection, documents[0], base.vector_scope))
    ]
    try:
        await asyncio.wait_for(created.wait(), timeout=10)
        tasks.extend(
            asyncio.create_task(store.insert_document(collection, document, base.vector_scope))
            for document in documents[1:]
        )
        # All contenders reach a real Postgres lock before the creator commits.
        # Before the fix they wait on its uncommitted catalog entry and then fail
        # uniqueness; afterward they wait on the DDL advisory lock and recheck.
        async with asyncio.timeout(10):
            async with engine.connect() as monitor:
                await monitor.execution_options(isolation_level="AUTOCOMMIT")
                # PostgreSQL lock state has no in-process notification event.
                while (  # noqa: ASYNC110
                    await monitor.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = :label AND wait_event_type = 'Lock'"
                        ),
                        {"label": label},
                    )
                    < 3
                ):
                    await asyncio.sleep(0.01)
        # An unrelated unfiled writer can finish while this DDL is paused.
        await asyncio.wait_for(
            store.insert_document(unrelated, _parsed("unrelated"), VectorScope(tenant=None)),
            timeout=10,
        )
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=15)
        if fail_first:
            assert isinstance(results[0], RuntimeError)
            assert str(results[0]) == "First DDL transaction rolls back"
            assert results[1:] == [None] * 3
        else:
            assert results == [None] * 4
        expected = documents[1:] if fail_first else documents
        async with engine.connect() as connection:
            query = text(f"SELECT parent_doc_id FROM {table}")  # noqa: S608 - UUID-generated table
            rows = (await connection.execute(query)).scalars().all()
            assert set(rows) == {document.id for document in expected}
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = :table"
                    ),
                    {"table": table},
                )
                == 1
            )
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        event.remove(writers.sync_engine, "after_cursor_execute", after_create)
        await writers.dispose()
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await connection.execute(text(f"DROP TABLE IF EXISTS rag_{unrelated}"))
