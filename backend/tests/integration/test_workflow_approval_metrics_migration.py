"""The 0235 revision, exercised at the row level.

0235 adds `edit_ratio` to `workflow_approvals`. The chain test never inserts a row, so it cannot
show a request made before it reading as unmeasured, the CHECK keeping the ratio between 0 and
1, or the downgrade dropping the column while keeping the request - this does, on a database of
its own for the reason `test_artifact_consent_migration` gives.
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

MIGRATION_DATABASE = f"agenticos_approval_metrics_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0234_workflow_outlook_trigger"
_TARGET_REVISION = "0235_workflow_approval_metrics"


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


def _seed_pending_request() -> uuid.UUID:
    """A pending request and the rows its foreign keys need, at the base revision."""
    user_id, org_id, workflow_id, run_id, node_run_id, approval_id = (
        uuid.uuid4() for _ in range(6)
    )
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
            "INSERT INTO workflows (id, organization_id, owner_user_id, visibility, slug, name, "
            "status, draft_revision) "
            "VALUES (:id, :org, :owner, 'private', 'wf', 'Workflow', 'draft', 0)",
            {"id": workflow_id, "org": org_id, "owner": user_id},
        ),
        (
            "INSERT INTO workflow_runs (id, organization_id, workflow_id, draft_graph_snapshot, "
            "mode, status, triggered_by, spent_cost, cost_is_partial, next_event_seq, "
            "root_run_id, visited_trigger_ids, depth) "
            "VALUES (:id, :org, :workflow, '{}'::jsonb, 'test', 'running', 'api', 0, false, 0, "
            ":id, '[]'::jsonb, 0)",
            {"id": run_id, "org": org_id, "workflow": workflow_id},
        ),
        (
            "INSERT INTO node_runs (id, organization_id, workflow_run_id, node_instance_id, "
            "scope_path, status) "
            "VALUES (:id, :org, :run, :instance, '[]'::jsonb, 'waiting')",
            {"id": node_run_id, "org": org_id, "run": run_id, "instance": uuid.uuid4()},
        ),
        (
            "INSERT INTO workflow_approvals (id, organization_id, workflow_id, workflow_run_id, "
            "node_run_id, title, approver_user_ids, status) "
            "VALUES (:id, :org, :workflow, :run, :node_run, 'Send the reply?', '[]'::jsonb, "
            "'pending')",
            {
                "id": approval_id,
                "org": org_id,
                "workflow": workflow_id,
                "run": run_id,
                "node_run": node_run_id,
            },
        ),
    )
    return approval_id


def test_an_existing_request_reads_unmeasured() -> None:
    _at_base()
    approval_id = _seed_pending_request()

    _alembic("upgrade", _TARGET_REVISION)

    assert (
        _scalar("SELECT edit_ratio IS NULL FROM workflow_approvals WHERE id = :id", id=approval_id)
        is True
    )
    assert (
        _scalar("SELECT status FROM workflow_approvals WHERE id = :id", id=approval_id) == "pending"
    )


def test_the_ratio_stays_between_zero_and_one() -> None:
    _at_base()
    approval_id = _seed_pending_request()
    _alembic("upgrade", _TARGET_REVISION)

    for ratio in (0, 1, 0.25):
        _execute(
            (
                "UPDATE workflow_approvals SET edit_ratio = :ratio WHERE id = :id",
                {"id": approval_id, "ratio": ratio},
            )
        )
    for ratio in (1.5, -0.1):
        with pytest.raises(IntegrityError):
            _execute(
                (
                    "UPDATE workflow_approvals SET edit_ratio = :ratio WHERE id = :id",
                    {"id": approval_id, "ratio": ratio},
                )
            )


def test_the_downgrade_drops_the_column_and_keeps_the_request() -> None:
    _at_base()
    approval_id = _seed_pending_request()
    _alembic("upgrade", _TARGET_REVISION)

    _alembic("downgrade", _BASE_REVISION)

    assert (
        _scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = "
            "'workflow_approvals' AND column_name = 'edit_ratio'"
        )
        == 0
    )
    assert (
        _scalar(
            "SELECT count(*) FROM pg_indexes WHERE indexname = "
            "'ix_workflow_approvals_org_workflow_created'"
        )
        == 0
    )
    assert (
        _scalar("SELECT status FROM workflow_approvals WHERE id = :id", id=approval_id) == "pending"
    )
