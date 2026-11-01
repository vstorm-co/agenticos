"""The 0240 revision, exercised at the row level.

It adds `workflow_log_alert_rules` and `workflow_log_alert_firings` and widens the CHECKs on
`notifications.event_type` and `notification_preferences.event_type` with `workflow_log_alert`.
The chain test never inserts a row, so it cannot show that the old CHECK refuses the new type
and the new one admits it, or that the downgrade removes the rows it would otherwise fail on -
this does, on a database of its own for the reason `test_artifact_share_requests_migration`
gives.
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

MIGRATION_DATABASE = f"agenticos_log_alerts_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0239_workflow_log_entry_seq"
_TARGET_REVISION = "0240_workflow_log_alerts"


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


def _run(*statements: tuple[str, dict[str, object]]) -> None:
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement, params in statements:
                conn.execute(text(statement), params)
    finally:
        engine.dispose()


def _count(sql: str) -> int:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(sql)).scalar_one())
    finally:
        engine.dispose()


def _seed() -> tuple[uuid.UUID, uuid.UUID]:
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    _run(
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
    )
    return user_id, org_id


def _insert_notifications(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    _run(
        (
            "INSERT INTO notifications (id, organization_id, recipient_user_id, event_type, "
            "occurrence_id, summary, in_app_visible) VALUES (:id, :org, :user, "
            "'workflow_log_alert', 'x', 'Too many errors.', true)",
            {"id": uuid.uuid4(), "org": org_id, "user": user_id},
        ),
        (
            "INSERT INTO notification_preferences (id, user_id, event_type, channel, enabled) "
            "VALUES (:id, :user, 'workflow_log_alert', 'in_app', false)",
            {"id": uuid.uuid4(), "user": user_id},
        ),
    )


def test_0240_adds_the_tables_and_the_event_type_and_the_downgrade_takes_them_away() -> None:
    _alembic("upgrade", _BASE_REVISION)
    user_id, org_id = _seed()
    with pytest.raises(IntegrityError):
        _insert_notifications(user_id, org_id)

    _alembic("upgrade", _TARGET_REVISION)
    _insert_notifications(user_id, org_id)
    assert _count("SELECT count(*) FROM notifications") == 1
    assert _count("SELECT count(*) FROM notification_preferences") == 1

    _alembic("downgrade", _BASE_REVISION)
    assert _count("SELECT count(*) FROM notifications") == 0
    assert _count("SELECT count(*) FROM notification_preferences") == 0
    with pytest.raises(IntegrityError):
        _insert_notifications(user_id, org_id)
    assert (
        _count(
            "SELECT count(*) FROM pg_tables "
            "WHERE tablename IN ('workflow_log_alert_rules', 'workflow_log_alert_firings')"
        )
        == 0
    )
