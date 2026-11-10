"""The 0173 revision, exercised on a queue that already holds eval jobs.

`tests/test_migrations.py` runs the chain on an empty database, where there is
no job to move. This writes `run-eval` jobs into the agent pool as the worker
before the revision did, upgrades, and asserts they moved to the eval pool and
nothing else did; then downgrades and asserts they are back.

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

MIGRATION_DATABASE = f"agenticos_eval_pool_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BEFORE = "0172_eval_run_suite_check"
_REVISION = "0173_eval_job_pool"


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


def _job(kind: str, status: str) -> uuid.UUID:
    job_id = uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO background_jobs (id, kind, pool, status, max_attempts) "
                    "VALUES (:id, :kind, 'agent', :status, 1)"
                ),
                {"id": job_id, "kind": kind, "status": status},
            )
    finally:
        engine.dispose()
    return job_id


def _pools() -> dict[uuid.UUID, str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, pool FROM background_jobs")).tuples().all()
    finally:
        engine.dispose()
    return dict(rows)


def test_eval_jobs_already_queued_move_to_the_eval_pool_and_back() -> None:
    """A queued eval would otherwise be claimed in the agent pool, and a dead one
    retried there: the worker reads the pool off the row."""
    _alembic("upgrade", _BEFORE)
    queued, dead = _job("run-eval", "queued"), _job("run-eval", "dead")
    agent_run = _job("run-agent", "queued")

    _alembic("upgrade", _REVISION)
    assert _pools() == {queued: "eval", dead: "eval", agent_run: "agent"}

    _alembic("downgrade", _BEFORE)
    assert _pools() == {queued: "agent", dead: "agent", agent_run: "agent"}

    _alembic("upgrade", "head")
