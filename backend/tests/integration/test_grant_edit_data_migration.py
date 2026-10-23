"""The 0145 revision, exercised at the row level.

It admits the grant level `edit_data` and keeps it to pages (`ck_resource_grant_level`,
`ck_resource_grant_edit_data_artifact`); its downgrade rewrites such grants to `edit` and
deletes none. The chain test never inserts a row, so it cannot show that the old CHECK
refuses the new level, that the new ones admit it for a page and refuse it anywhere else,
or that the downgrade keeps the grants it would otherwise fail on - this does, on a
database of its own for the reason `test_artifact_consent_migration` gives.
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

MIGRATION_DATABASE = f"agenticos_grant_edit_data_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0198_artifact_share_requests"
_TARGET_REVISION = "0199_grant_edit_data"


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


def _grant(user_id: uuid.UUID, org_id: uuid.UUID, *, resource_type: str, level: str) -> None:
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO resource_grants (id, organization_id, subject_user_id, "
                "resource_type, resource_id, level) VALUES "
                "(:id, :org, :user, :type, :resource, :level)",
                {
                    "id": uuid.uuid4(),
                    "org": org_id,
                    "user": user_id,
                    "type": resource_type,
                    "resource": uuid.uuid4(),
                    "level": level,
                },
            ),
        )
    )


def _levels() -> list[tuple[str, str]]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT resource_type, level FROM resource_grants ORDER BY created_at, id")
            )
            return [(row[0], row[1]) for row in rows]
    finally:
        engine.dispose()


def test_0145_admits_edit_data_for_pages_only_and_the_downgrade_lowers_it_to_edit() -> None:
    _at_base()
    user_id, org_id = _seed_at_base()
    with pytest.raises(IntegrityError):
        _grant(user_id, org_id, resource_type="artifact", level="edit_data")

    _alembic("upgrade", _TARGET_REVISION)
    _grant(user_id, org_id, resource_type="artifact", level="edit_data")
    _grant(user_id, org_id, resource_type="artifact", level="edit")
    _grant(user_id, org_id, resource_type="agent", level="edit")
    for refused in ("agent", "collection", "workflow"):
        with pytest.raises(IntegrityError):
            _grant(user_id, org_id, resource_type=refused, level="edit_data")
    with pytest.raises(IntegrityError):
        _grant(user_id, org_id, resource_type="artifact", level="owner")

    _alembic("downgrade", _BASE_REVISION)
    # Every grant is kept; the one that was `edit_data` is an `edit` now.
    assert _levels() == [("artifact", "edit"), ("artifact", "edit"), ("agent", "edit")]
    with pytest.raises(IntegrityError):
        _grant(user_id, org_id, resource_type="artifact", level="edit_data")
