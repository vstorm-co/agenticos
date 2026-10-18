"""Migration `0142_voice_calls`: runs read as text, and the call table comes and goes.

A run that exists before the upgrade was typed, so it must read `text`; the
call table must be created with its foreign keys and dropped cleanly. Run here
against real PostgreSQL, on a scratch database holding only the tables the
revision references.
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

SCRATCH_DATABASE = f"agenticos_voice_calls_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0142_voice_calls.py"


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
    spec = importlib.util.spec_from_file_location("voice_calls_migration", _MIGRATION)
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


_REFERENCED = (
    "organizations",
    "agents",
    "users",
    "conversations",
    "agent_embeds",
    "organization_secrets",
)


def test_an_existing_run_reads_text_and_the_call_table_goes_back(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS voice_calls, agent_runs CASCADE"))
        for table in _REFERENCED:
            connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            connection.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE agent_runs (id uuid PRIMARY KEY)"))
        connection.execute(text("INSERT INTO agent_runs VALUES (gen_random_uuid())"))

    _run(engine, "upgrade")
    with engine.begin() as connection:
        modality = connection.execute(text("SELECT modality FROM agent_runs")).scalar_one()
        tables = set(inspect(connection).get_table_names())

    assert modality == "text"
    assert "voice_calls" in tables

    _run(engine, "downgrade")
    with engine.begin() as connection:
        names = {found["name"] for found in inspect(connection).get_columns("agent_runs")}
        tables = set(inspect(connection).get_table_names())

    assert names == {"id"}
    assert "voice_calls" not in tables
