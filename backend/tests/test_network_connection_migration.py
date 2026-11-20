"""Upgrade and guarded rollback preserve identities and queued network work."""

import importlib.util
import os
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

_DATABASE = f"agenticos_tailscale_migration_test_p{os.getpid()}"
_MIGRATION = Path(__file__).parents[1] / "alembic/versions/0347_network_connections.py"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _outside_transaction(statement: str) -> None:
    engine = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def migration_engine() -> Iterator[Engine]:
    probe = create_engine(_url("postgres"))
    try:
        try:
            with probe.connect():
                pass
        except Exception:
            pytest.skip("No test PostgreSQL server is reachable")
    finally:
        probe.dispose()
    drop = f'DROP DATABASE IF EXISTS "{_DATABASE}" WITH (FORCE)'
    _outside_transaction(drop)
    _outside_transaction(f'CREATE DATABASE "{_DATABASE}"')
    engine = create_engine(_url(_DATABASE))
    try:
        yield engine
    finally:
        engine.dispose()
        _outside_transaction(drop)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("network_connections_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(engine: Engine, direction: str) -> None:
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        getattr(_migration(), direction)()


def test_upgrade_and_downgrade_refuse_to_discard_connections_or_network_jobs(
    migration_engine: Engine,
) -> None:
    """Even completed network jobs block rollback; unrelated job rows survive it."""
    engine = migration_engine
    organization_id, user_id, connection_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        for name in ("organizations", "users", "sessions"):
            connection.execute(text(f"CREATE TABLE {name} (id uuid PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE background_jobs (id integer PRIMARY KEY, pool text NOT NULL, "
                "status text NOT NULL, CONSTRAINT background_jobs_pool_check "
                "CHECK (pool IN ('agent', 'eval', 'ingest', 'system', 'workflow')))"
            )
        )
        connection.execute(text("INSERT INTO background_jobs VALUES (1, 'system', 'succeeded')"))
        connection.execute(text("INSERT INTO organizations VALUES (:id)"), {"id": organization_id})
        connection.execute(text("INSERT INTO users VALUES (:id)"), {"id": user_id})

    _run(engine, "upgrade")
    with engine.begin() as connection:
        assert "network_connections" in inspect(connection).get_table_names()
        connection.execute(
            text(
                "INSERT INTO network_connections "
                "(id, organization_id, owner_user_id, scope, visibility, name, state_payload) "
                "VALUES (:id, :org, :owner, 'user', 'private', 'Laptop', 'sealed-identity')"
            ),
            {"id": connection_id, "org": organization_id, "owner": user_id},
        )
    with pytest.raises(RuntimeError, match="Cannot discard"):
        _run(engine, "downgrade")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT state_payload FROM network_connections")) == (
            "sealed-identity"
        )
        connection.execute(text("DELETE FROM network_connections"))
        connection.execute(text("INSERT INTO background_jobs VALUES (2, 'network', 'succeeded')"))

    with pytest.raises(RuntimeError, match="Cannot discard"):
        _run(engine, "downgrade")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM background_jobs")) == 2
        connection.execute(text("DELETE FROM background_jobs WHERE id = 2"))
    _run(engine, "downgrade")
    with engine.begin() as connection:
        assert "network_connections" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT id, pool FROM background_jobs")).all() == [
            (1, "system")
        ]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("INSERT INTO background_jobs VALUES (3, 'network', 'queued')"))
