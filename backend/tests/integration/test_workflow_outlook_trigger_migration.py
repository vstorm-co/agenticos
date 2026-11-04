"""The 0234 revision, exercised at the row level.

0234 adds `outlook` to the `workflow_exposures.adapter` CHECK, to its shape CHECK (no secret,
clock, link or bot) and to the `workflow_runs.triggered_by` CHECK. The chain test never inserts
a row, so it cannot show the new value accepted only from 0234 on, the shape refusing a bot,
or the downgrade refusing while an Outlook exposure or run exists - this does, on a database
of its own for the reason `test_artifact_consent_migration` gives.
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

MIGRATION_DATABASE = f"agenticos_outlook_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0233_workflow_approval_proposal"
_TARGET_REVISION = "0234_workflow_outlook_trigger"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str, expect_failure: bool = False) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": MIGRATION_DATABASE},
        timeout=120,
    )
    if expect_failure:
        assert result.returncode != 0, f"alembic {' '.join(args)} should have failed"
        return result.stderr
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"
    return result.stderr


def _at_base() -> None:
    """Put the shared database at the base revision whatever an earlier test left it at."""
    _alembic("upgrade", _TARGET_REVISION)
    # The downgrade refuses while an Outlook row exists, and an earlier test may have left one.
    _execute(
        ("DELETE FROM workflow_exposures WHERE adapter = 'outlook'", {}),
        ("DELETE FROM workflow_runs WHERE triggered_by = 'outlook'", {}),
    )
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


def _seed() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """An organization, a workflow with one published version and a member, at any revision."""
    user_id, org_id, workflow_id, version_id = (uuid.uuid4() for _ in range(4))
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
            "INSERT INTO workflow_versions (id, workflow_id, organization_id, version, graph) "
            "VALUES (:id, :workflow, :org, 1, '{}'::jsonb)",
            {"id": version_id, "workflow": workflow_id, "org": org_id},
        ),
    )
    return org_id, workflow_id, version_id, user_id


def _insert_exposure(
    seed: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    adapter: str,
    *,
    channel_bot_id: uuid.UUID | None = None,
) -> None:
    """A no-secret, no-clock exposure, the shape a mailbox adapter has."""
    org_id, workflow_id, version_id, user_id = seed
    _execute(
        (
            "INSERT INTO workflow_exposures (id, organization_id, workflow_id, "
            "workflow_version_id, node_instance_id, adapter, execution_principal_user_id, "
            "is_active, run_input, channel_bot_id) "
            "VALUES (:id, :org, :workflow, :version, :node, :adapter, :user, true, "
            "'{}'::jsonb, :bot)",
            {
                "id": uuid.uuid4(),
                "org": org_id,
                "workflow": workflow_id,
                "version": version_id,
                "node": uuid.uuid4(),
                "adapter": adapter,
                "user": user_id,
                "bot": channel_bot_id,
            },
        ),
    )


def _insert_run(org_id: uuid.UUID, workflow_id: uuid.UUID, triggered_by: str) -> None:
    run_id = uuid.uuid4()
    _execute(
        (
            "INSERT INTO workflow_runs (id, organization_id, workflow_id, draft_graph_snapshot, "
            "mode, status, triggered_by, spent_cost, cost_is_partial, next_event_seq, "
            "root_run_id, visited_trigger_ids, depth) "
            "VALUES (:id, :org, :workflow, '{}'::jsonb, 'test', 'succeeded', :by, 0, false, 0, "
            ":id, '[]'::jsonb, 0)",
            {"id": run_id, "org": org_id, "workflow": workflow_id, "by": triggered_by},
        ),
    )


def test_outlook_is_refused_before_0234_and_taken_from_it() -> None:
    _at_base()
    seed = _seed()
    with pytest.raises(IntegrityError, match="ck_workflow_exposure_adapter"):
        _insert_exposure(seed, "outlook")
    with pytest.raises(IntegrityError):
        _insert_run(seed[0], seed[1], "outlook")

    _alembic("upgrade", _TARGET_REVISION)

    _insert_exposure(seed, "outlook")
    _insert_run(seed[0], seed[1], "outlook")
    _insert_run(seed[0], seed[1], "gmail")
    _insert_run(seed[0], seed[1], "app")
    with pytest.raises(IntegrityError):
        _insert_run(seed[0], seed[1], "nonsense")


def test_an_outlook_exposure_carries_no_bot() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    seed = _seed()
    _execute(
        (
            "INSERT INTO channel_bots (id, organization_id, platform, name, "
            "token_encrypted, secret_key_version, is_active, webhook_mode, access_policy) "
            "VALUES (:id, :org, 'telegram', 'bot', 'x', 1, true, false, '{}'::json)",
            {"id": (bot := uuid.uuid4()), "org": seed[0]},
        ),
    )

    with pytest.raises(IntegrityError, match="ck_workflow_exposure_shape"):
        _insert_exposure(seed, "outlook", channel_bot_id=bot)


def test_the_downgrade_succeeds_with_no_outlook_row() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    seed = _seed()
    _insert_exposure(seed, "gmail")
    _insert_run(seed[0], seed[1], "gmail")

    _alembic("downgrade", _BASE_REVISION)

    # A fresh workflow, so the one-exposure-per-workflow rule cannot be what refuses it.
    with pytest.raises(IntegrityError, match="ck_workflow_exposure_adapter"):
        _insert_exposure(_seed(), "outlook")


def test_the_downgrade_refuses_while_an_outlook_exposure_exists() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    seed = _seed()
    _insert_exposure(seed, "outlook")

    stderr = _alembic("downgrade", _BASE_REVISION, expect_failure=True)

    assert "violated by some row" in stderr
    assert _scalar("SELECT count(*) FROM workflow_exposures WHERE adapter = 'outlook'") == 1


def test_the_downgrade_refuses_while_an_outlook_run_exists() -> None:
    _at_base()
    _alembic("upgrade", _TARGET_REVISION)
    seed = _seed()
    _insert_run(seed[0], seed[1], "outlook")

    stderr = _alembic("downgrade", _BASE_REVISION, expect_failure=True)

    assert "violated by some row" in stderr
    assert _scalar("SELECT count(*) FROM workflow_runs WHERE triggered_by = 'outlook'") == 1
