"""The 0146 and 0147 revisions, exercised at the row level.

0146 adds `organizations.public_live_data`, off for every row that exists; 0147 adds the
four `public_data_*` columns on `artifacts` and the CHECK that keeps a consent from naming
no membership. The chain test never inserts a row, so it cannot show the default reaching an
existing organization, the CHECK refusing what it should, the foreign key letting go of a
deleted user, or the downgrade taking the columns away - this does, on a database of its own
for the reason `test_artifact_consent_migration` gives.
"""

from __future__ import annotations

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

MIGRATION_DATABASE = f"agenticos_public_data_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0145_grant_edit_data"
_TARGET_REVISION = "0147_artifact_public_data"


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


def _insert_artifact(
    org_id: uuid.UUID,
    *,
    fingerprint: str | None,
    membership: uuid.UUID | None,
    by: uuid.UUID | None,
) -> uuid.UUID:
    artifact_id = uuid.uuid4()
    _outside_a_transaction_with(
        (
            (
                "INSERT INTO artifacts (id, organization_id, name, title, visibility, "
                "public_data_fingerprint, public_data_membership_id, public_data_by_user_id) "
                "VALUES (:id, :org, :name, 'Pipeline', 'private', :fp, :membership, :by)",
                {
                    "id": artifact_id,
                    "org": org_id,
                    "name": f"p-{uuid.uuid4().hex[:8]}",
                    "fp": fingerprint,
                    "membership": membership,
                    "by": by,
                },
            ),
        )
    )
    return artifact_id


def _scalar(sql: str, **params: object) -> object:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql), params).scalar_one()
    finally:
        engine.dispose()


def test_0146_adds_the_switch_off_for_organizations_that_exist_and_the_downgrade_removes_it() -> (
    None
):
    _at_base()
    _, org_id = _seed_at_base()

    _alembic("upgrade", "0146_org_public_live_data")
    assert _scalar("SELECT public_live_data FROM organizations WHERE id = :id", id=org_id) is False

    _alembic("downgrade", _BASE_REVISION)
    assert (
        _scalar(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'organizations' AND column_name = 'public_live_data'"
        )
        == 0
    )


def test_0147_adds_the_columns_and_the_check_and_the_downgrade_takes_them_away() -> None:
    _at_base()
    user_id, org_id = _seed_at_base()
    _alembic("upgrade", _TARGET_REVISION)

    # A consent names the membership it was given under, or there is none.
    with pytest.raises(IntegrityError):
        _insert_artifact(org_id, fingerprint="a" * 64, membership=None, by=user_id)
    bare = _insert_artifact(org_id, fingerprint=None, membership=None, by=None)
    giver = _second_user()
    consented = _insert_artifact(org_id, fingerprint="a" * 64, membership=uuid.uuid4(), by=giver)
    assert bare != consented

    # The person who gave it going away leaves the consent, with nobody named.
    _outside_a_transaction_with((("DELETE FROM users WHERE id = :id", {"id": giver}),))
    assert (
        _scalar(
            "SELECT public_data_by_user_id IS NULL AND public_data_fingerprint IS NOT NULL "
            "FROM artifacts WHERE id = :id",
            id=consented,
        )
        is True
    )

    _alembic("downgrade", _BASE_REVISION)
    assert (
        _scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = 'artifacts' "
            "AND column_name LIKE 'public_data_%'"
        )
        == 0
    )
