"""Migration `0154_dictation_compressed_audio`: the switch arrives off, and leaves cleanly.

The row a deployment already holds has to read as off after the upgrade - raw
PCM is the format whose length cannot lie, and accepting the others is a risk
somebody takes on the settings page, never one an upgrade takes for them. So
the revision runs here against real PostgreSQL, on a scratch database holding
only the one table it touches.
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

SCRATCH_DATABASE = f"agenticos_dictation_audio_test_p{os.getpid()}"
_MIGRATION = (
    Path(__file__).parents[1] / "alembic" / "versions" / "0154_dictation_compressed_audio.py"
)


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
    spec = importlib.util.spec_from_file_location("dictation_audio_migration", _MIGRATION)
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


def test_the_row_a_deployment_holds_reads_as_off_and_the_column_goes_back(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS deployment_settings"))
        connection.execute(
            text("CREATE TABLE deployment_settings (id int PRIMARY KEY, app_name text)")
        )
        connection.execute(text("INSERT INTO deployment_settings VALUES (1, 'Acme')"))

    _run(engine, "upgrade")
    with engine.begin() as connection:
        stored = connection.execute(
            text("SELECT dictation_compressed_audio FROM deployment_settings")
        ).scalar_one()
        column = next(
            found
            for found in inspect(connection).get_columns("deployment_settings")
            if found["name"] == "dictation_compressed_audio"
        )
        # A row written without naming it - the singleton upsert's first insert.
        connection.execute(text("INSERT INTO deployment_settings (id) VALUES (2)"))
        inserted = connection.execute(
            text("SELECT dictation_compressed_audio FROM deployment_settings WHERE id = 2")
        ).scalar_one()

    assert (stored, inserted, column["nullable"]) == (False, False, False)

    _run(engine, "downgrade")
    with engine.begin() as connection:
        names = {found["name"] for found in inspect(connection).get_columns("deployment_settings")}

    assert names == {"id", "app_name"}
