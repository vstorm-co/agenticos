"""The 0149 revision's downgrade, exercised on a drafter that existed before it ran.

`tests/test_migrations.py` runs the chain over empty tables, so a downgrade that
left the drafter's `system_key` on an ordinary agent would pass it - and the next
upgrade would find an agent anybody may chat with under the drafter's key. This
upgrades to 0149, seeds a drafter, downgrades one step, reads the row and
upgrades again.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does: it runs real migrations, and pointing
that at the model-built integration database (or a developer's) is how a run
empties something it should not.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_knowledge_gaps_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_REVISION = "0149_knowledge_gaps"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": MIGRATION_DATABASE},
        timeout=120,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


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


def _seed_drafter() -> uuid.UUID:
    user_id, org_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
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
                    "(id, organization_id, slug, name, status, visibility, kind, system_key) "
                    "VALUES (:id, :org, 'knowledge-gap-drafter', 'Knowledge gap drafter', "
                    "'draft', 'org', 'drafter', 'knowledge_gap_drafter')"
                ),
                {"id": agent_id, "org": org_id},
            )
    finally:
        engine.dispose()
    return agent_id


def _kind_and_key(agent_id: uuid.UUID) -> tuple[str, str | None]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT kind, system_key FROM agents WHERE id = :id"), {"id": agent_id}
            ).one()
    finally:
        engine.dispose()
    return row.kind, row.system_key


def test_a_downgraded_drafter_is_an_ordinary_agent_holding_no_system_key() -> None:
    _alembic("upgrade", _REVISION)
    drafter = _seed_drafter()

    _alembic("downgrade", "-1")
    after = _kind_and_key(drafter)
    _alembic("upgrade", _REVISION)

    assert after == ("agent", None)
    assert _kind_and_key(drafter) == ("agent", None)
