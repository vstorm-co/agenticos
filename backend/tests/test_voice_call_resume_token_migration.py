"""Migration `0158_voice_call_resume_token`: the column comes and goes, and old rows stay.

Run against real PostgreSQL, on a scratch database holding only a `voice_calls`
with a row from before the revision.
"""

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

SCRATCH_DATABASE = f"agenticos_voice_call_resume_token_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0158_voice_call_resume_token.py"


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
    spec = importlib.util.spec_from_file_location("voice_call_resume_token_migration", _MIGRATION)
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


def _columns(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        return {column["name"] for column in inspect(connection).get_columns("voice_calls")}


def test_a_connection_from_before_has_no_token_and_the_column_goes_back(engine: Engine) -> None:
    """Nothing is backfilled: a connection opened before the revision cannot be resumed."""
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS voice_calls"))
        connection.execute(text("CREATE TABLE voice_calls (id uuid PRIMARY KEY)"))
        connection.execute(text("INSERT INTO voice_calls (id) VALUES (gen_random_uuid())"))

    _run(engine, "upgrade")
    assert "resume_token_hash" in _columns(engine)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT resume_token_hash FROM voice_calls")).all() == [
            (None,)
        ]

    _run(engine, "downgrade")
    assert _columns(engine) == {"id"}
