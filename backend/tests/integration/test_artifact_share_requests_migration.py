"""The 0144 revision, exercised at the row level.

It adds `artifact_share_requests` and widens the CHECKs on `notifications.event_type` and
`notification_preferences.event_type` with `artifact_share_requested`. The chain test never
inserts a row, so it cannot show that the table's CHECKs and its two partial unique
indexes refuse what they should, that the old CHECK refuses the new type and the new one
admits it, or that the downgrade removes the rows it would otherwise fail on - this does,
on a database of its own for the reason `test_artifact_consent_migration` gives.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from functools import partial

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_artifact_requests_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0197_artifact_owner_changed"
_TARGET_REVISION = "0198_artifact_share_requests"


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


def _insert_notifications(user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO notifications (id, organization_id, recipient_user_id, event_type, "
                "occurrence_id, summary, in_app_visible) VALUES (:id, :org, :user, "
                "'artifact_share_requested', 'x', 'Somebody asked.', true)",
                {"id": uuid.uuid4(), "org": org_id, "user": user_id},
            ),
            (
                "INSERT INTO notification_preferences (id, user_id, event_type, channel, enabled) "
                "VALUES (:id, :user, 'artifact_share_requested', 'in_app', false)",
                {"id": uuid.uuid4(), "user": user_id},
            ),
        )
    )


def _insert_artifact(org_id: uuid.UUID) -> uuid.UUID:
    artifact_id = uuid.uuid4()
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO artifacts (id, organization_id, name, title, visibility) "
                "VALUES (:id, :org, 'pipeline', 'Pipeline', 'private')",
                {"id": artifact_id, "org": org_id},
            ),
        )
    )
    return artifact_id


def _insert_request(
    artifact_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    kind: str = "audience",
    status: str = "pending",
    visibility: str | None = None,
    note: str | None = None,
) -> None:
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO artifact_share_requests (id, organization_id, artifact_id, kind, "
                "requester_user_id, status, requested_visibility, note) VALUES "
                "(:id, :org, :artifact, :kind, :user, :status, :visibility, :note)",
                {
                    "id": uuid.uuid4(),
                    "org": org_id,
                    "artifact": artifact_id,
                    "kind": kind,
                    "user": user_id,
                    "status": status,
                    "visibility": visibility,
                    "note": note,
                },
            ),
        )
    )


def _count(sql: str) -> int:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return int(conn.execute(text(sql)).scalar_one())
    finally:
        engine.dispose()


def _second_user() -> uuid.UUID:
    user_id = uuid.uuid4()
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO users (id, email, is_active, is_app_admin) "
                "VALUES (:id, :email, true, false)",
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            ),
        )
    )
    return user_id


def test_0144_adds_the_table_and_the_event_type_and_the_downgrade_takes_them_away() -> None:
    _at_base()
    user_id, org_id = _seed_at_base()
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
    assert _count("SELECT count(*) FROM pg_tables WHERE tablename = 'artifact_share_requests'") == 0


def test_the_table_refuses_what_its_checks_and_indexes_hold_out() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    user_id, org_id = _seed_at_base()
    other = _second_user()
    artifact_id = _insert_artifact(org_id)

    for refused in (
        partial(_insert_request, kind="everyone"),
        partial(_insert_request, status="maybe"),
        partial(_insert_request, visibility="private"),
        partial(_insert_request, note="x" * 501),
    ):
        with pytest.raises(IntegrityError):
            refused(artifact_id, org_id, user_id)
    _insert_request(artifact_id, org_id, user_id, visibility="org", note="x" * 500)

    # One pending request per person, page and kind...
    with pytest.raises(IntegrityError):
        _insert_request(artifact_id, org_id, user_id)
    _insert_request(artifact_id, org_id, user_id, kind="access")
    _insert_request(artifact_id, org_id, other)
    _insert_request(artifact_id, org_id, user_id, status="voided")
    _insert_request(artifact_id, org_id, user_id, status="declined")
    # ... and one pending version request per page, whoever made it.
    _insert_request(artifact_id, org_id, user_id, kind="version")
    with pytest.raises(IntegrityError):
        _insert_request(artifact_id, org_id, other, kind="version")
    _insert_request(artifact_id, org_id, other, kind="version", status="approved")

    assert _count("SELECT count(*) FROM artifact_share_requests") == 7
    _outside_a_transaction_with((("DELETE FROM artifacts WHERE id = :id", {"id": artifact_id}),))
    assert _count("SELECT count(*) FROM artifact_share_requests") == 0
