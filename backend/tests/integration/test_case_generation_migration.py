"""The 0165 revision's downgrade, exercised with a seeded case generator in place.

`tests/test_migrations.py` runs the whole chain forwards and back on an empty
database, where no generator exists to violate the narrower `ck_agent_kind` the
downgrade restores. This seeds one, downgrades a step, and asserts it is kept as
a plain agent without its `system_key`, then upgrades again.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_case_gen_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_REVISION = "0165_case_generation"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _env() -> dict[str, str]:
    return {**os.environ, "POSTGRES_DB": MIGRATION_DATABASE}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env=_env(),
        timeout=120,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"
    return result


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


@pytest.fixture(scope="module", autouse=True)
def migration_database() -> Iterator[None]:
    maintenance = _url(_MAINTENANCE_DATABASE)
    if not _server_reachable(maintenance):
        if os.getenv("CI"):
            raise RuntimeError(
                f"No database reachable at {maintenance} but CI is set - refusing to skip."
            )
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{MIGRATION_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{MIGRATION_DATABASE}"')
    try:
        yield
    finally:
        _outside_a_transaction(maintenance, drop)


def _seed_generator() -> uuid.UUID:
    """One organization's seeded case generator, as the runner leaves it."""
    agent_id, user_id, org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, :email, true, false)"
                ),
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, name, slug, created_by_user_id, is_personal, chat_may_waive_approvals) "
                    "VALUES (:id, :name, :slug, :owner, false, false)"
                ),
                {
                    "id": org_id,
                    "name": "Acme",
                    "slug": f"acme-{uuid.uuid4().hex[:8]}",
                    "owner": user_id,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO agents "
                    "(id, organization_id, slug, name, visibility, status, kind, system_key) "
                    "VALUES (:id, :org, 'case-generator', 'Case generator', 'org', 'draft', "
                    "'generator', 'case_generator')"
                ),
                {"id": agent_id, "org": org_id},
            )
    finally:
        engine.dispose()
    return agent_id


def _agent(agent_id: uuid.UUID) -> tuple[str, str | None]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            kind, key = conn.execute(
                text("SELECT kind, system_key FROM agents WHERE id = :id"), {"id": agent_id}
            ).one()
    finally:
        engine.dispose()
    return kind, key


def test_the_downgrade_keeps_a_generator_as_a_plain_agent() -> None:
    _alembic("upgrade", _REVISION)
    agent_id = _seed_generator()

    _alembic("downgrade", "-1")

    assert _agent(agent_id) == ("agent", None)
    _alembic("upgrade", _REVISION)
    assert _agent(agent_id) == ("agent", None)
