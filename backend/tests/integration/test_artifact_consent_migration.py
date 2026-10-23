"""The 0142 revision, exercised at the row level.

`tests/test_migrations.py` runs the whole chain forwards and back; it never inserts a
row at a revision, so it cannot show what the backfill makes of a version already
there. This does: upgrade to 0141, insert a page with a version that reads no data and
one bound to a table, upgrade to 0142, and assert the bound one waits for consent with
the digest `artifact_bindings.fingerprint` gives it - not `not_needed`, which would
have handed its data to everyone who opens the page - then downgrade and assert the
columns are gone.

It owns a database of its own, for the reason `test_workflow_run_public_origin_migration`
does: the model-built integration database already has the columns.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings
from app.schemas.artifact import ArtifactBinding, BindingReach
from app.services.artifact_bindings import fingerprint

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_artifact_consent_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0195_approval_capability_tool"
_TARGET_REVISION = "0196_artifact_consent"
_TABLE, _STAGE = uuid.uuid4(), uuid.uuid4()
_BINDING = ArtifactBinding(
    name="deals",
    table_id=_TABLE,
    limit=10,
    fields={"stage": _STAGE},
    reach=BindingReach(tables={_TABLE: {_STAGE: 0}}),
)


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


def _seed_versions_at_base() -> dict[str, uuid.UUID]:
    """A page at revision 0141 with a plain version and a bound one."""
    user_id, org_id, artifact_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    versions = {"plain": uuid.uuid4(), "bound": uuid.uuid4()}
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
                    "INSERT INTO artifacts (id, organization_id, owner_user_id, visibility, "
                    "name, title) VALUES (:id, :org, :owner, 'private', 'pipeline', 'Pipeline')"
                ),
                {"id": artifact_id, "org": org_id, "owner": user_id},
            )
            for number, (kind, version_id) in enumerate(versions.items(), start=1):
                bindings = [_BINDING.model_dump(mode="json")] if kind == "bound" else []
                conn.execute(
                    text(
                        "INSERT INTO artifact_versions (id, artifact_id, number, media_type, "
                        "size_bytes, sha256, storage_path, bindings) VALUES (:id, :artifact, "
                        ":number, 'text/html', 1, :sha, 'artifacts/x.html', "
                        "CAST(:bindings AS jsonb))"
                    ),
                    {
                        "id": version_id,
                        "artifact": artifact_id,
                        "number": number,
                        "sha": f"{number:064d}",
                        "bindings": json.dumps(bindings),
                    },
                )
    finally:
        engine.dispose()
    return versions


def _columns(table: str) -> set[str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            ).all()
    finally:
        engine.dispose()
    return {row[0] for row in rows}


def test_0142_holds_a_bound_version_already_there_to_its_owner_s_consent() -> None:
    _alembic("upgrade", _BASE_REVISION)
    versions = _seed_versions_at_base()

    _alembic("upgrade", _TARGET_REVISION)

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            stored = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    text("SELECT id, consent_state, query_fingerprint FROM artifact_versions")
                ).tuples()
            }
            auto_consent = conn.execute(text("SELECT auto_consent FROM artifacts")).scalar_one()
    finally:
        engine.dispose()
    assert stored[versions["plain"]] == ("not_needed", None)
    assert stored[versions["bound"]] == ("pending", fingerprint([_BINDING]))
    assert auto_consent is False


def test_0142_downgrade_drops_every_column_it_added() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    assert {"consent_state", "query_fingerprint"} <= _columns("artifact_versions")

    _alembic("downgrade", _BASE_REVISION)

    assert not {
        "published_by_user_id",
        "published_by_membership_id",
        "query_fingerprint",
        "consent_state",
        "consented_at",
        "consented_by_user_id",
        "consented_by_membership_id",
        "consent_automatic",
        "consent_via_grant",
    } & _columns("artifact_versions")
    assert not {"auto_consent", "consent_withdrawn_at"} & _columns("artifacts")
