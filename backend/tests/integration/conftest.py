"""Fixtures for tests that need a real database.

These tests exist because a mock cannot tell you whether a `CHECK` constraint
rejects a row, whether a cascade deletes what it should, or whether a partial
unique index actually prevents a second default. Those are the guarantees the
schema is supposed to provide, and the only way to know is to ask Postgres.

The database belongs to this pytest process alone: it is created here and
dropped again when the session ends. `drop_all` below is unconditional, so a
shared name meant two runs on one machine demolishing each other's tables
mid-test - deadlocks between one run's `DROP TABLE` and another's `CREATE
INDEX`, a column that "does not exist" on a database that had it, and two runs
of the same commit reporting different failures (#189). `tests/conftest.py`
derives the per-process name; this module owns its lifecycle.

The whole module is skipped when no database is reachable, so `make test` on a
laptop without Docker still runs everything else.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncGenerator, Iterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base

# Where to connect to issue `CREATE DATABASE` / `DROP DATABASE`, neither of
# which can run from inside the database it names. Every Postgres image this
# project uses ships it.
_MAINTENANCE_DATABASE = "postgres"


def _database_url(name: str) -> str:
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _outside_a_transaction(url: str, statement: str) -> None:
    """Run one statement with no transaction around it.

    `CREATE DATABASE` and `DROP DATABASE` are refused inside one, and SQLAlchemy
    opens a transaction for anything else.
    """
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(statement)
    finally:
        await engine.dispose()


# Names a database is allowed to have before this suite will drop its tables.
# The guard exists because the cost of getting it wrong is somebody's local
# data, silently, in the middle of an ordinary `pytest` run - and the name comes
# from the environment, one variable away from being a real database.
_TEST_DATABASE_MARKERS = ("test", "ci")

# What may reach `CREATE DATABASE "…"`. The name is interpolated into DDL, so
# anything that is not a plain identifier is refused rather than quoted and
# hoped about.
_PLAIN_IDENTIFIER = re.compile(r"[A-Za-z0-9_]+")


def _refuse_a_real_database(name: str) -> None:
    """Refuse to run against a database that is not obviously a test one.

    `drop_all` here is unconditional and this module drops the database itself
    afterwards, so pointing the suite at a development database destroys it.
    Nothing in the fixture can tell the difference once it has happened; the only
    moment it can be caught is before the first drop. The per-process suffix is
    appended before this runs, so what is checked is the name that will actually
    be dropped.
    """
    if not _PLAIN_IDENTIFIER.fullmatch(name):
        raise RuntimeError(
            f"Refusing to create a database named {name!r}: the name is interpolated into "
            "DDL, so it has to be a plain identifier - letters, digits and underscores."
        )
    if not any(marker in name.lower() for marker in _TEST_DATABASE_MARKERS):
        raise RuntimeError(
            f"Refusing to run integration tests against {name!r}: this suite drops every "
            "table before each test, and the database itself afterwards. Point POSTGRES_DB "
            "at a database whose name contains 'test' or 'ci'."
        )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A database created for this pytest process, and dropped when it exits.

    Session-scoped and synchronous: a session-scoped *async* fixture cannot
    depend on anyio's per-function backend fixture, and `asyncio.run` gives each
    statement a loop of its own, so nothing is shared with the loops the tests
    run in.

    The drop before the create reclaims a leftover from an earlier run that was
    killed outright - the only way one survives, since the teardown below runs
    even when the suite fails.
    """
    name = os.environ["POSTGRES_DB"]
    _refuse_a_real_database(name)

    maintenance = _database_url(_MAINTENANCE_DATABASE)
    if not asyncio.run(_reachable(maintenance)):
        # Skipping is right on a laptop with no Docker. In CI it is not: the
        # service container is declared, so an unreachable database means it
        # failed to start - and silently skipping two hundred tests would keep
        # the build green while nothing that needs a database ran at all. This
        # suite is the only thing that checks constraints, cascades and
        # cross-tenant reads, so that green would be meaningless.
        if os.getenv("CI"):
            raise RuntimeError(
                f"No database reachable at {maintenance} but CI is set. The Postgres "
                "service container did not come up; refusing to skip the integration "
                "suite and report a green build."
            )
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
    asyncio.run(_outside_a_transaction(maintenance, drop))
    asyncio.run(_outside_a_transaction(maintenance, f'CREATE DATABASE "{name}"'))
    try:
        yield _database_url(name)
    finally:
        # FORCE because a connection outliving its engine would otherwise turn
        # cleanup into an error and leave the database behind. Nobody else ever
        # connects to it, so there is nobody else to disconnect.
        asyncio.run(_outside_a_transaction(maintenance, drop))


@pytest.fixture
async def engine(database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """An engine on that database, with the schema freshly built from the models.

    The schema is created from the models rather than by running migrations:
    these tests assert what the *code* believes the schema is. Whether the
    migrations arrive at the same place is a separate question, answered by
    `make test-migrations`.

    Function-scoped rather than session-scoped: anyio's backend fixture is
    per-function, and a session-scoped async fixture cannot depend on it.
    Recreating the schema costs a fraction of a second and buys complete
    isolation between tests.
    """
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """A session rolled back after each test, so tests cannot affect each other."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
