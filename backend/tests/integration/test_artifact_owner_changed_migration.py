"""The 0143 revision, exercised at the row level.

It widens the CHECKs on `notifications.event_type` and `notification_preferences.
event_type` with `artifact_owner_changed`. The chain test never inserts a row, so it
cannot show that the old CHECK refuses the new type, that the new one admits it, or that
the downgrade removes the rows it would otherwise fail on - this does, on a database of
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

MIGRATION_DATABASE = f"agenticos_artifact_owner_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0196_artifact_consent"
_TARGET_REVISION = "0197_artifact_owner_changed"


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


def _seed_at_base() -> tuple[uuid.UUID, uuid.UUID]:
    """A user and an organization at the base revision."""
    user_id, org_id = uuid.uuid4(), uuid.uuid4()
    _outside_a_transaction_with(
        (
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
    )
    return user_id, org_id


def _outside_a_transaction_with(statements: tuple[tuple[str, dict[str, object]], ...]) -> None:
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement, params in statements:
                conn.execute(text(statement), params)
    finally:
        engine.dispose()


def _insert_owner_changed(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO notifications (id, organization_id, recipient_user_id, event_type, "
                "occurrence_id, summary, in_app_visible) VALUES (:id, :org, :user, "
                "'artifact_owner_changed', 'x', 'A page changed hands.', true)",
                {"id": uuid.uuid4(), "org": org_id, "user": user_id},
            ),
            (
                "INSERT INTO notification_preferences (id, user_id, event_type, channel, enabled) "
                "VALUES (:id, :user, 'artifact_owner_changed', 'in_app', false)",
                {"id": uuid.uuid4(), "user": user_id},
            ),
        )
    )


_COUNTS = {
    "notifications": "SELECT count(*) FROM notifications",
    "notification_preferences": "SELECT count(*) FROM notification_preferences",
}


def _count(table: str) -> int:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(_COUNTS[table])).scalar_one())
    finally:
        engine.dispose()


def test_0143_admits_the_new_event_type_and_its_downgrade_removes_its_rows() -> None:
    _alembic("upgrade", _BASE_REVISION)
    user_id, org_id = _seed_at_base()
    with pytest.raises(IntegrityError):
        _insert_owner_changed(user_id, org_id)

    _alembic("upgrade", _TARGET_REVISION)
    _insert_owner_changed(user_id, org_id)
    assert (_count("notifications"), _count("notification_preferences")) == (1, 1)

    _alembic("downgrade", _BASE_REVISION)
    assert (_count("notifications"), _count("notification_preferences")) == (0, 0)
    with pytest.raises(IntegrityError):
        _insert_owner_changed(user_id, org_id)
