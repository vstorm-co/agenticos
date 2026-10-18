"""Migration `0143_org_voice_settings`: voice arrives off, with the default limits.

An organization that exists before the upgrade must not start taking calls
because of it: the switch reads off, and the limits read their defaults. So the
revision runs here against real PostgreSQL, on a scratch database holding only
the one table it touches.
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

SCRATCH_DATABASE = f"agenticos_org_voice_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0143_org_voice_settings.py"


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
    spec = importlib.util.spec_from_file_location("org_voice_migration", _MIGRATION)
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


def test_an_existing_organization_reads_voice_off_and_the_columns_go_back(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS organizations"))
        connection.execute(text("CREATE TABLE organizations (id int PRIMARY KEY, name text)"))
        connection.execute(text("INSERT INTO organizations VALUES (1, 'Acme')"))

    _run(engine, "upgrade")
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT voice_conversations_enabled, voice_in_chat, voice_max_call_seconds, "
                "voice_monthly_minutes FROM organizations"
            )
        ).one()

    assert tuple(row) == (False, True, 600, 600)

    _run(engine, "downgrade")
    with engine.begin() as connection:
        names = {found["name"] for found in inspect(connection).get_columns("organizations")}

    assert names == {"id", "name"}
