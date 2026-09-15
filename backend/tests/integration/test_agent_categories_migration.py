"""The 0081 revision, exercised at the row and index level.

`tests/test_migrations.py` runs the whole chain forwards and back; it never
inserts a row at a revision or inspects a column or index, so it cannot show
that a pre-existing agent gains an empty array, that the two indexes are GIN, or
that the downgrade removes both. This does: upgrade to 0080, insert an agent,
upgrade to 0081, assert the defaults and the `gin` access method, then downgrade
and assert the columns and indexes are gone.

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

MIGRATION_DATABASE = f"agenticos_agent_cats_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0080_audit_checkpoints"
_TARGET_REVISION = "0081_agent_categories_tags"


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


def _seed_agent_at_base() -> uuid.UUID:
    """Insert one agent at revision 0080, before the new columns exist."""
    agent_id = uuid.uuid4()
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
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
                    "INSERT INTO agents (id, organization_id, slug, name, visibility, status) "
                    "VALUES (:id, :org, :slug, :name, 'private', 'draft')"
                ),
                {"id": agent_id, "org": org_id, "slug": "support", "name": "Support"},
            )
    finally:
        engine.dispose()
    return agent_id


def _index_access_methods() -> dict[str, str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.relname, am.amname FROM pg_class c "
                    "JOIN pg_am am ON am.oid = c.relam "
                    "WHERE c.relname IN ('ix_agents_categories', 'ix_agents_tags')"
                )
            ).all()
    finally:
        engine.dispose()
    return dict(rows)


def _agent_columns() -> set[str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'agents'"
                )
            ).all()
    finally:
        engine.dispose()
    return {row[0] for row in rows}


def test_the_revision_adds_empty_arrays_and_gin_indexes_then_removes_them() -> None:
    _alembic("upgrade", _BASE_REVISION)
    agent_id = _seed_agent_at_base()
    assert "categories" not in _agent_columns()

    _alembic("upgrade", _TARGET_REVISION)

    # The pre-existing row gets an empty array in each new column, not null.
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            categories, tags = conn.execute(
                text("SELECT categories, tags FROM agents WHERE id = :id"), {"id": agent_id}
            ).one()
    finally:
        engine.dispose()
    assert categories == []
    assert tags == []
    assert _index_access_methods() == {
        "ix_agents_categories": "gin",
        "ix_agents_tags": "gin",
    }

    _alembic("downgrade", _BASE_REVISION)
    columns = _agent_columns()
    assert "categories" not in columns
    assert "tags" not in columns
    assert _index_access_methods() == {}
