"""The 0137 revision, exercised at the row level.

`tests/test_migrations.py` runs the whole chain forwards and back; it never
inserts a row at a revision, so it cannot show which runs already there the
backfill marks. This does: upgrade to 0136, insert a webhook run's chain and an
API run's, upgrade to 0137, assert every run under the public root is marked and
no other run is, then downgrade and assert the column is gone.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does: it runs real migrations, and the
model-built integration database already has the column, so the revision's
`add_column` could not run there at all.
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

MIGRATION_DATABASE = f"agenticos_run_public_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0136_artifact_bindings"
_TARGET_REVISION = "0137_workflow_run_public_origin"


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


def _seed_runs_at_base() -> dict[str, uuid.UUID]:
    """Two chains at revision 0136, before the column exists: a webhook root with
    a called child and a table run under it, and an API root with a called child."""
    user_id, org_id, workflow_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    webhook, api = uuid.uuid4(), uuid.uuid4()
    runs = {
        "webhook": (webhook, "webhook", webhook),
        "webhook_child": (uuid.uuid4(), "workflow_call", webhook),
        "webhook_table": (uuid.uuid4(), "table_created", webhook),
        "api": (api, "api", api),
        "api_child": (uuid.uuid4(), "workflow_call", api),
    }
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
                    "VALUES (:id, 'Acme', :slug, :owner, false, false)"
                ),
                {"id": org_id, "slug": f"acme-{uuid.uuid4().hex[:8]}", "owner": user_id},
            )
            conn.execute(
                text(
                    "INSERT INTO workflows "
                    "(id, organization_id, owner_user_id, visibility, slug, name, status, "
                    "draft_revision) "
                    "VALUES (:id, :org, :owner, 'private', 'wf', 'Workflow', 'draft', 0)"
                ),
                {"id": workflow_id, "org": org_id, "owner": user_id},
            )
            # Roots first: a child's `root_run_id` references its root.
            for run_id, triggered_by, root_run_id in sorted(
                runs.values(), key=lambda run: run[0] != run[2]
            ):
                conn.execute(
                    text(
                        "INSERT INTO workflow_runs "
                        "(id, organization_id, workflow_id, draft_graph_snapshot, mode, status, "
                        "triggered_by, spent_cost, cost_is_partial, next_event_seq, "
                        "root_run_id, visited_trigger_ids, depth) "
                        "VALUES (:id, :org, :workflow, '{}'::jsonb, 'test', 'succeeded', "
                        ":triggered_by, 0, false, 0, :root, '[]'::jsonb, 0)"
                    ),
                    {
                        "id": run_id,
                        "org": org_id,
                        "workflow": workflow_id,
                        "triggered_by": triggered_by,
                        "root": root_run_id,
                    },
                )
    finally:
        engine.dispose()
    return {name: run[0] for name, run in runs.items()}


def _run_columns() -> set[str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'workflow_runs'"
                )
            ).all()
    finally:
        engine.dispose()
    return {row[0] for row in rows}


def test_0137_marks_every_run_under_a_public_root() -> None:
    _alembic("upgrade", _BASE_REVISION)
    runs = _seed_runs_at_base()
    assert "public_origin" not in _run_columns()

    _alembic("upgrade", _TARGET_REVISION)

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            stored = dict(
                conn.execute(text("SELECT id, public_origin FROM workflow_runs")).tuples().all()
            )
    finally:
        engine.dispose()
    assert {name: stored[run_id] for name, run_id in runs.items()} == {
        "webhook": True,
        "webhook_child": True,
        "webhook_table": True,
        "api": False,
        "api_child": False,
    }


def test_0137_downgrade_drops_the_column() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    assert "public_origin" in _run_columns()

    _alembic("downgrade", _BASE_REVISION)

    assert "public_origin" not in _run_columns()
