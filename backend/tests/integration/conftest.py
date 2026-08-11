"""Fixtures for tests that need a real database.

These tests exist because a mock cannot tell you whether a `CHECK` constraint
rejects a row, whether a cascade deletes what it should, or whether a partial
unique index actually prevents a second default. Those are the guarantees the
schema is supposed to provide, and the only way to know is to ask Postgres.

The database belongs to this pytest process alone: it is created here and
dropped again when the session ends. The per-process name is what keeps two
runs on one machine off each other's tables - without it a shared name once had
them demolishing each other mid-test, back when each test rebuilt the schema
with `drop_all` + `create_all` and the collision was a deadlock between one
run's `DROP TABLE` and another's `CREATE INDEX`, a column that "does not exist"
on a database that had it, and two runs of the same commit reporting different
failures (#189). The schema is built once now and the reset between tests is
`TRUNCATE` (#215), so that DDL deadlock can no longer happen - but the
per-process name still earns its place. `tests/conftest.py` derives it; this
module owns its lifecycle.

The whole module is skipped when no database is reachable, so `make test` on a
laptop without Docker still runs everything else.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncGenerator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base
from app.db.session import engine as app_engine

# Where to connect to issue `CREATE DATABASE` / `DROP DATABASE`, neither of
# which can run from inside the database it names. Every Postgres image this
# project uses ships it.
_MAINTENANCE_DATABASE = "postgres"


def _database_url(name: str) -> str:
    """Where the application would connect, with the database name replaced.

    Every part but the name comes from `settings`, so this engine and the one in
    `app/db/session.py` cannot disagree about where they are connecting or as
    whom. They did: this function defaulted the password to "postgres" while
    `app/core/config.py` defaults it to empty, which no test could see until one
    drove the application's engine directly and failed to authenticate on any
    checkout without a `backend/.env` (#485). `tests/conftest.py` seeds the
    fallback, in the only place that still precedes the settings object.
    """
    return (
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{name}"
    )


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

    The reset between tests `TRUNCATE`s every table unconditionally and this
    module drops the database itself afterwards, so pointing the suite at a
    development database destroys it. Nothing in the fixture can tell the
    difference once it has happened; the only moment it can be caught is before
    the first of those runs. The per-process suffix is appended before this runs,
    so what is checked is the name that will actually be dropped.
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


async def _create_schema(url: str) -> None:
    """Build the schema from the models, once, on a loop of its own."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def schema_url(database_url: str) -> str:
    """The suite's database URL, with the schema built from the models once.

    The schema is created from the models rather than by running migrations:
    these tests assert what the *code* believes the schema is. Whether the
    migrations arrive at the same place is a separate question, answered by
    `make test-migrations`.

    Session-scoped and synchronous for the same reason `database_url` is: a
    session-scoped *async* fixture cannot depend on anyio's per-function backend
    fixture, and `asyncio.run` gives the build a loop of its own. `create_all`
    with no `drop_all` before it is enough because `database_url` hands over a
    database that was just created - there is nothing to drop.

    This is the whole of #215: the schema used to be rebuilt in the
    function-scoped `engine` fixture below (`drop_all` + `create_all` before
    *every* test), ~0.4s of DDL that was very nearly the entire runtime of a
    suite whose assertions are microseconds of Postgres work. Built once here,
    the `engine` fixture only has to empty the data between tests.
    """
    asyncio.run(_create_schema(database_url))
    return database_url


async def _reset(engine: AsyncEngine) -> None:
    """Return the database to the modelled schema with every table empty.

    `TRUNCATE ... RESTART IDENTITY CASCADE` over every model table empties them
    in one statement, no DDL and no ordering to get right. Unlike rolling back a
    transaction it also clears rows a test committed through the real
    `get_db_session` - which the API-flow tests in `test_platform_flows.py` and
    the dispatch-ordering tests do by design, so a rollback-only reset would not
    be enough on its own.

    A test may also create a table *outside* the models - a runtime
    `rag_<collection>`, one of the ordering probes. Those are dropped first, so
    each test starts from the modelled schema and nothing else regardless of the
    order the suite ran in.
    """
    async with engine.begin() as connection:
        present = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        modelled = set(Base.metadata.tables)
        # `name` is a live identifier from `pg_tables` and each table name below
        # comes from `Base.metadata` - both are developer-controlled identifiers,
        # not user input, and neither DROP nor TRUNCATE can bind them as
        # parameters, so they are quoted and interpolated.
        for name in (row[0] for row in present if row[0] not in modelled):
            await connection.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def engine(schema_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """An engine on the suite's database, with every table emptied first.

    Function-scoped because anyio's backend fixture is: the reset has to run on
    the same per-function event loop the test does. The schema itself is built
    once by `schema_url`; here each test is handed a clean slate cheaply, by
    emptying the data rather than rebuilding the schema (#215).

    The application's own engine is disposed first. It is a module-level object,
    so its pool outlives the test that filled it, while anyio gives each test an
    event loop of its own - and a connection created on a loop that has since
    closed answers the next statement issued through it with `InterfaceError:
    another operation is in progress`, from whichever unlucky test checked it
    out. The tests that drive the real `get_db_session` used to each dispose it
    on the way out, which only covers the pair of them; disposing on the way *in*
    covers every test that could be handed one, whatever ran before it in this
    worker. Disposing an empty pool costs nothing, which is the common case.
    """
    await app_engine.dispose()
    engine = create_async_engine(schema_url)
    await _reset(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """A session rolled back after each test, so tests cannot affect each other."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
