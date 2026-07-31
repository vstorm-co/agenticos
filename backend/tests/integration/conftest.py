"""Fixtures for tests that need a real database.

These tests exist because a mock cannot tell you whether a `CHECK` constraint
rejects a row, whether a cascade deletes what it should, or whether a partial
unique index actually prevents a second default. Those are the guarantees the
schema is supposed to provide, and the only way to know is to ask Postgres.

The whole module is skipped when no database is reachable, so `make test` on a
laptop without Docker still runs everything else.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base


def _database_url() -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    name = os.getenv("POSTGRES_DB", "test_db")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


async def _reachable() -> bool:
    engine = create_async_engine(_database_url())
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


# Names a database is allowed to have before this suite will drop its tables.
# The guard exists because the cost of getting it wrong is somebody's local
# data, silently, in the middle of an ordinary `pytest` run - and the default
# (`test_db`) is one environment variable away from being a real database.
_TEST_DATABASE_MARKERS = ("test", "ci")


def _refuse_a_real_database(url: str) -> None:
    """Refuse to run against a database that is not obviously a test one.

    `drop_all` here is unconditional, so pointing this suite at a development
    database destroys it. Nothing in the fixture can tell the difference
    afterwards; the only moment it can be caught is before the first drop.
    """
    name = url.rsplit("/", 1)[-1]
    if not any(marker in name.lower() for marker in _TEST_DATABASE_MARKERS):
        raise RuntimeError(
            f"Refusing to run integration tests against {name!r}: this suite drops every "
            "table before each test. Point POSTGRES_DB at a database whose name contains "
            "'test' or 'ci'."
        )


@pytest.fixture
async def engine():
    """A database engine, or skip the module.

    The schema is created from the models rather than by running migrations:
    these tests assert what the *code* believes the schema is. Whether the
    migrations arrive at the same place is a separate question, answered by
    `make test-migrations`.

    Function-scoped rather than session-scoped: anyio's backend fixture is
    per-function, and a session-scoped async fixture cannot depend on it.
    Recreating the schema costs a fraction of a second and buys complete
    isolation between tests.
    """
    if not await _reachable():
        # Skipping is right on a laptop with no Docker. In CI it is not: the
        # service container is declared, so an unreachable database means it
        # failed to start - and silently skipping two hundred tests would keep
        # the build green while nothing that needs a database ran at all. This
        # suite is the only thing that checks constraints, cascades and
        # cross-tenant reads, so that green would be meaningless.
        if os.getenv("CI"):
            raise RuntimeError(
                f"No database reachable at {_database_url()} but CI is set. The Postgres "
                "service container did not come up; refusing to skip the integration "
                "suite and report a green build."
            )
        pytest.skip("No database reachable - start one with `make docker-db`")

    _refuse_a_real_database(_database_url())

    engine = create_async_engine(_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    """A session rolled back after each test, so tests cannot affect each other."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
