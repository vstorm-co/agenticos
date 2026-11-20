"""Concurrent benchmark runs cannot rebuild a collection another run is measuring."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.locks import LockScope, hold_name, hold_name_within
from tests.test_retrieval_eval import run

pytestmark = pytest.mark.anyio


@pytest.fixture
async def evaluation_connections(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[None]:
    # Match the harness's dedicated connections: returning a pooled connection
    # would retain a session lock after the context exits.
    dedicated = create_async_engine(engine.url, poolclass=NullPool)

    @asynccontextmanager
    async def connection() -> AsyncGenerator[AsyncConnection]:
        async with dedicated.connect() as current:
            yield current

    monkeypatch.setattr(run, "get_worker_connection", connection)
    try:
        yield
    finally:
        await dedicated.dispose()


async def test_a_collection_remains_reserved_across_commits_until_the_run_exits(
    evaluation_connections: None,
) -> None:
    name = f"eval_{uuid4().hex}"
    async with run.collection_locks([name]):
        with pytest.raises(SystemExit, match="Another retrieval evaluation"):
            async with run.collection_locks([name]):
                pass
        async with run.collection_locks([name + "_other"]):
            pass

    async with run.collection_locks([name]):
        pass


async def test_a_refused_run_releases_any_collections_it_already_reserved(
    evaluation_connections: None,
) -> None:
    prefix = f"eval_{uuid4().hex}"
    async with run.collection_locks([prefix + "_b"]):
        with pytest.raises(SystemExit, match="Another retrieval evaluation"):
            async with run.collection_locks([prefix + "_a", prefix + "_b"]):
                pass
        async with run.collection_locks([prefix + "_a"]):
            pass


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_an_interrupted_run_releases_its_collections(
    evaluation_connections: None, failure: type[BaseException]
) -> None:
    name = f"eval_{uuid4().hex}"
    with pytest.raises(failure):
        async with run.collection_locks([name]):
            raise failure()

    async with run.collection_locks([name]):
        pass


async def test_an_evaluation_blocks_collection_claims_but_allows_its_own_shared_writes(
    evaluation_connections: None,
    engine: AsyncEngine,
) -> None:
    name = f"eval_{uuid4().hex}"
    async with AsyncSession(engine) as db:
        async with run.collection_locks([name]):
            assert not await hold_name_within(db, LockScope.COLLECTION_TEARDOWN, name, wait_ms=25)
            assert await db.scalar(
                select(
                    func.pg_try_advisory_xact_lock_shared(
                        LockScope.COLLECTION_TEARDOWN.value, func.hashtext(name)
                    )
                )
            )
            await db.rollback()
        assert await hold_name_within(db, LockScope.COLLECTION_TEARDOWN, name, wait_ms=25)


async def test_an_existing_collection_claim_refuses_an_evaluation_and_releases_its_locks(
    evaluation_connections: None,
    engine: AsyncEngine,
) -> None:
    name = f"eval_{uuid4().hex}"
    async with AsyncSession(engine) as db:
        await hold_name(db, LockScope.COLLECTION_TEARDOWN, name)
        with pytest.raises(SystemExit, match="knowledge-base operation"):
            async with run.collection_locks([name]):
                pass
        await db.rollback()
    async with run.collection_locks([name]):
        pass
