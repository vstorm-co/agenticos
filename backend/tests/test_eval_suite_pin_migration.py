"""Migration `0182_eval_suite_pin`: the guards already set up are pinned to what they read.

The backfill lives only in the migration's SQL. It runs here against real
PostgreSQL on a scratch database holding only the tables it reads, so a guard
left unpinned - reading whatever its dataset turns into - fails a test rather
than a promotion.
"""

import importlib.util
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, text

from app.core.config import settings

SCRATCH_DATABASE = f"agenticos_eval_suite_pin_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0182_eval_suite_pin.py"
_TABLES = (
    "CREATE TABLE datasets (id uuid PRIMARY KEY, latest_version int NOT NULL, scoring jsonb)",
    "CREATE TABLE eval_suites (id uuid PRIMARY KEY, dataset_id uuid NOT NULL)",
    "CREATE TABLE agent_environment_guards (environment_id uuid, suite_id uuid NOT NULL)",
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
    spec = importlib.util.spec_from_file_location("eval_suite_pin_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine() -> Iterator[Engine]:
    maintenance = _url("postgres")
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")
    drop = f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{SCRATCH_DATABASE}"')
    scratch = create_engine(_url(SCRATCH_DATABASE))
    try:
        with scratch.begin() as connection:
            for table in _TABLES:
                connection.execute(text(table))
        yield scratch
    finally:
        scratch.dispose()
        _outside_a_transaction(maintenance, drop)


def _dataset(connection, *, latest: int, scoring: dict) -> uuid.UUID:
    dataset_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO datasets VALUES (:id, :latest, CAST(:scoring AS jsonb))"),
        {"id": dataset_id, "latest": latest, "scoring": json.dumps(scoring)},
    )
    return dataset_id


def _suite(connection, dataset_id: uuid.UUID, *, guards: bool) -> uuid.UUID:
    suite_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO eval_suites VALUES (:id, :dataset)"),
        {"id": suite_id, "dataset": dataset_id},
    )
    if guards:
        connection.execute(
            text("INSERT INTO agent_environment_guards VALUES (:env, :suite)"),
            {"env": uuid.uuid4(), "suite": suite_id},
        )
    return suite_id


def test_upgrade_pins_each_guard_to_what_its_dataset_holds_and_nothing_else(
    engine: Engine,
) -> None:
    scoring = {"checks": {"enabled": True, "required": True}}
    with engine.begin() as connection:
        filled = _dataset(connection, latest=3, scoring=scoring)
        empty = _dataset(connection, latest=0, scoring=scoring)
        guard = _suite(connection, filled, guards=True)
        loose = _suite(connection, filled, guards=False)
        on_empty = _suite(connection, empty, guards=True)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        pins = {
            row.id: (row.pinned_dataset_version, row.pinned_scoring)
            for row in connection.execute(
                text("SELECT id, pinned_dataset_version, pinned_scoring FROM eval_suites")
            )
        }

    assert pins[guard] == (3, scoring)
    assert pins[loose] == (None, None)
    # Pinned to no version it would pass on nothing; it is pinned once it can be.
    assert pins[on_empty] == (None, None)


def test_downgrade_takes_the_pin_away(engine: Engine) -> None:
    with engine.begin() as connection:
        guard = _suite(connection, _dataset(connection, latest=1, scoring={}), guards=True)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
            _migration().downgrade()
        columns = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'eval_suites'"
                )
            )
        }
        assert (
            connection.execute(
                text("SELECT id FROM eval_suites WHERE id = :id"), {"id": guard}
            ).scalar_one()
            == guard
        )

    assert columns == {"id", "dataset_id"}
