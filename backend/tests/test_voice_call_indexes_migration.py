"""Migration `0144_voice_call_indexes`: each indexed column comes and goes.

Run against real PostgreSQL, on a scratch database holding only a `voice_calls`
with the columns the revision indexes.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, inspect, text

from app.core.config import settings

SCRATCH_DATABASE = f"agenticos_voice_call_indexes_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0144_voice_call_indexes.py"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _outside_a_transaction(url: str, statement: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _server_reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("voice_call_indexes_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    maintenance = _url("postgres")
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")
    drop = f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{SCRATCH_DATABASE}"')
    scratch = create_engine(_url(SCRATCH_DATABASE))
    try:
        yield scratch
    finally:
        scratch.dispose()
        _outside_a_transaction(maintenance, drop)


def _run(engine: Engine, direction: str) -> None:
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        getattr(_migration(), direction)()


_INDEXED = ("agent_id", "conversation_id", "embed_id", "secret_id", "resume_of")


def _indexes(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        return {index["name"] for index in inspect(connection).get_indexes("voice_calls")}


def test_the_lookup_columns_are_indexed_and_the_indexes_go_back(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS voice_calls"))
        columns = ", ".join(f"{column} uuid" for column in _INDEXED)
        connection.execute(text(f"CREATE TABLE voice_calls (id uuid PRIMARY KEY, {columns})"))

    _run(engine, "upgrade")
    assert _indexes(engine) == {f"voice_calls_{column}_idx" for column in _INDEXED}

    _run(engine, "downgrade")
    assert _indexes(engine) == set()
