"""The 0148 revision, exercised at the row level.

0148 adds `artifact_versions.actions`, `workflow_runs.source_artifact_id` and
`source_version_number`, and widens the `triggered_by` CHECK with `app`. The chain test
never inserts a row, so it cannot show the default reaching a version that exists, the CHECK
taking `app` only from 0148 on, the foreign key letting go of a deleted page while the run
stays, or the downgrade turning `app` runs into `api` ones before it narrows the CHECK -
this does, on a database of its own for the reason `test_artifact_consent_migration` gives.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_actions_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0220_artifact_public_data"
_TARGET_REVISION = "0221_artifact_actions"


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


def _at_base() -> None:
    """Put the shared database at the base revision whatever an earlier test left it at."""
    _alembic("upgrade", _TARGET_REVISION)
    _alembic("downgrade", _BASE_REVISION)


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


def _execute(*statements: tuple[str, dict[str, object]]) -> None:
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement, params in statements:
                conn.execute(text(statement), params)
    finally:
        engine.dispose()


def _scalar(sql: str, **params: object) -> object:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar_one()
    finally:
        engine.dispose()


def _seed() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An organization, a page with one version and a workflow, at whichever revision."""
    user_id, org_id, page_id, workflow_id = (uuid.uuid4() for _ in range(4))
    _execute(
        (
            "INSERT INTO users (id, email, is_active, is_app_admin) "
            "VALUES (:id, :email, true, false)",
            {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
        ),
        (
            "INSERT INTO organizations "
            "(id, name, slug, created_by_user_id, is_personal, chat_may_waive_approvals) "
            "VALUES (:id, 'Acme', :slug, :owner, false, false)",
            {"id": org_id, "slug": f"acme-{uuid.uuid4().hex[:8]}", "owner": user_id},
        ),
        (
            "INSERT INTO artifacts (id, organization_id, name, title, visibility) "
            "VALUES (:id, :org, :name, 'Tool', 'private')",
            {"id": page_id, "org": org_id, "name": f"p-{uuid.uuid4().hex[:8]}"},
        ),
        (
            "INSERT INTO artifact_versions "
            "(id, artifact_id, number, media_type, size_bytes, sha256, storage_path) "
            "VALUES (:id, :page, 1, 'text/html', 1, :sha, 'a/b')",
            {"id": uuid.uuid4(), "page": page_id, "sha": "a" * 64},
        ),
        (
            "INSERT INTO workflows (id, organization_id, owner_user_id, visibility, slug, name, "
            "status, draft_revision) "
            "VALUES (:id, :org, :owner, 'private', 'wf', 'Workflow', 'draft', 0)",
            {"id": workflow_id, "org": org_id, "owner": user_id},
        ),
    )
    return org_id, page_id, workflow_id


def _insert_run(
    org_id: uuid.UUID,
    workflow_id: uuid.UUID,
    triggered_by: str,
    *,
    page_id: uuid.UUID | None = None,
    version_number: int | None = None,
) -> uuid.UUID:
    """A run at the target revision when a page is named, since the columns exist only there."""
    run_id = uuid.uuid4()
    params: dict[str, object] = {
        "id": run_id,
        "org": org_id,
        "workflow": workflow_id,
        "by": triggered_by,
    }
    if page_id is None:
        statement = (
            "INSERT INTO workflow_runs (id, organization_id, workflow_id, draft_graph_snapshot, "
            "mode, status, triggered_by, spent_cost, cost_is_partial, next_event_seq, "
            "root_run_id, visited_trigger_ids, depth) "
            "VALUES (:id, :org, :workflow, '{}'::jsonb, 'test', 'succeeded', :by, 0, false, 0, "
            ":id, '[]'::jsonb, 0)"
        )
    else:
        statement = (
            "INSERT INTO workflow_runs (id, organization_id, workflow_id, draft_graph_snapshot, "
            "mode, status, triggered_by, spent_cost, cost_is_partial, next_event_seq, "
            "root_run_id, visited_trigger_ids, depth, source_artifact_id, source_version_number) "
            "VALUES (:id, :org, :workflow, '{}'::jsonb, 'test', 'succeeded', :by, 0, false, 0, "
            ":id, '[]'::jsonb, 0, :page, :version)"
        )
        params |= {"page": page_id, "version": version_number}
    _execute((statement, params))
    return run_id


def test_a_version_that_exists_declares_no_actions_and_the_downgrade_takes_the_columns() -> None:
    _at_base()
    _, page_id, _ = _seed()

    _alembic("upgrade", _TARGET_REVISION)
    assert (
        _scalar("SELECT actions::text FROM artifact_versions WHERE artifact_id = :id", id=page_id)
        == "[]"
    )

    _alembic("downgrade", _BASE_REVISION)
    assert (
        _scalar(
            "SELECT count(*) FROM information_schema.columns WHERE "
            "(table_name = 'artifact_versions' AND column_name = 'actions') "
            "OR (table_name = 'workflow_runs' AND column_name LIKE 'source_%')"
        )
        == 0
    )


def test_the_trigger_check_takes_app_only_from_0148_on() -> None:
    _at_base()
    org_id, _, workflow_id = _seed()
    with pytest.raises(IntegrityError):
        _insert_run(org_id, workflow_id, "app")

    _alembic("upgrade", _TARGET_REVISION)

    _insert_run(org_id, workflow_id, "app")
    with pytest.raises(IntegrityError):
        _insert_run(org_id, workflow_id, "nonsense")


def test_a_deleted_page_leaves_its_runs_with_nothing_named() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    org_id, page_id, workflow_id = _seed()
    run_id = _insert_run(org_id, workflow_id, "app", page_id=page_id, version_number=3)

    _execute(("DELETE FROM artifacts WHERE id = :id", {"id": page_id}))

    assert (
        _scalar(
            "SELECT source_artifact_id IS NULL AND source_version_number = 3 "
            "FROM workflow_runs WHERE id = :id",
            id=run_id,
        )
        is True
    )
    # Indexed, as the other foreign keys on the table are.
    assert (
        _scalar(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'workflow_runs' "
            "AND indexname = 'workflow_runs_source_artifact_id_idx'"
        )
        == 1
    )


def test_the_downgrade_turns_app_runs_into_api_runs_before_narrowing_the_check() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    org_id, page_id, workflow_id = _seed()
    run_id = _insert_run(org_id, workflow_id, "app", page_id=page_id, version_number=1)
    other = _insert_run(org_id, workflow_id, "webhook")

    _alembic("downgrade", _BASE_REVISION)

    assert _scalar("SELECT triggered_by FROM workflow_runs WHERE id = :id", id=run_id) == "api"
    assert _scalar("SELECT triggered_by FROM workflow_runs WHERE id = :id", id=other) == "webhook"
