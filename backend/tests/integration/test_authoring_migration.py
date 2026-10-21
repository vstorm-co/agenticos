"""The 0152 revision: the authoring assistant's tables, and a downgrade that keeps the improver.

Upgraded, an improver agent and its proposals can be stored. Downgraded, the
proposal tables go and the improver stays as an ordinary agent - its kind back
to `agent`, its system key cleared - so the narrower constraint holds and an
edited agent is not deleted. Upgrading again works over that row. It owns a
database of its own, as every migration test here does.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_authoring_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0151_eval_suites"
_TARGET_REVISION = "0152_authoring_proposals"


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


def _seed_improver() -> uuid.UUID:
    """An organization at 0152 with a seeded improver and a request it answered."""
    agent_id = uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            user_id, org_id = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, :email, true, false)"
                ),
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_by_user_id, "
                    "is_personal, chat_may_waive_approvals) "
                    "VALUES (:id, 'Acme', :slug, :owner, false, false)"
                ),
                {"id": org_id, "slug": f"acme-{uuid.uuid4().hex[:8]}", "owner": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO agents (id, organization_id, slug, name, visibility, status, "
                    "draft_spec, kind, system_key) VALUES (:id, :org, :slug, "
                    "'Authoring assistant', 'org', 'draft', CAST(:spec AS jsonb), "
                    "'improver', 'authoring_improver')"
                ),
                {
                    "id": agent_id,
                    "org": org_id,
                    "slug": f"improver-{uuid.uuid4().hex[:8]}",
                    "spec": json.dumps({"name": "Authoring assistant"}),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO authoring_requests (id, organization_id, kind, target, "
                    "agent_id, status, estimate_usd, cost_usd, window_days, evidence) "
                    "VALUES (:id, :org, 'improve', 'agent', :agent, 'completed', 0, 0, 30, "
                    "'{}'::jsonb)"
                ),
                {"id": uuid.uuid4(), "org": org_id, "agent": agent_id},
            )
    finally:
        engine.dispose()
    return agent_id


def test_a_downgrade_keeps_the_improver_as_an_ordinary_agent() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    agent_id = _seed_improver()

    _alembic("downgrade", _BASE_REVISION)

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            kind, key = conn.execute(
                text("SELECT kind, system_key FROM agents WHERE id = :id"), {"id": agent_id}
            ).one()
            gone = conn.execute(text("SELECT to_regclass('authoring_requests')")).scalar_one()
    finally:
        engine.dispose()
    assert (kind, key) == ("agent", None)
    assert gone is None

    _alembic("upgrade", _TARGET_REVISION)
