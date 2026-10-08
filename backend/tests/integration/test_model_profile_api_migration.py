"""The 0104 revision's backfill, exercised on rows that existed before it.

`tests/test_migrations.py` runs the chain over empty tables, so an inverted
backfill would pass it while moving every vLLM or LiteLLM profile onto the
Responses API and a 400 on every request. This upgrades to 0103, inserts a
profile of every shape, upgrades to 0104 and reads which API each one got.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does: it runs real migrations, and pointing
that at the model-built integration database (or a developer's) is how a run
empties something it should not.
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

MIGRATION_DATABASE = f"agenticos_profile_api_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0103_skill_library_fingerprint"
_TARGET_REVISION = "0104_model_profile_api"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _env() -> dict[str, str]:
    return {**os.environ, "POSTGRES_DB": MIGRATION_DATABASE}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env=_env(),
        timeout=120,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"
    return result


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


_SHAPES = {
    "openai on its own endpoint": ("openai", None),
    "openai behind a vLLM": ("openai", "http://vllm:8000/v1"),
    "azure": ("azure", None),
    "anthropic": ("anthropic", None),
    "anthropic behind a gateway": ("anthropic", "https://gateway.example/v1"),
}


def _seed_profiles_at_base() -> None:
    """Insert one profile of every shape at 0103, before the column exists."""
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()
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
                    "VALUES (:id, :name, :slug, :owner, false, false)"
                ),
                {
                    "id": org_id,
                    "name": "Acme",
                    "slug": f"acme-{uuid.uuid4().hex[:8]}",
                    "owner": user_id,
                },
            )
            for label, (provider, base_url) in _SHAPES.items():
                conn.execute(
                    text(
                        "INSERT INTO model_profiles "
                        "(id, organization_id, label, provider, model, base_url) "
                        "VALUES (:id, :org, :label, :provider, 'm', :base_url)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "org": org_id,
                        "label": label,
                        "provider": provider,
                        "base_url": base_url,
                    },
                )
    finally:
        engine.dispose()


def _apis() -> dict[str, str | None]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT label, api FROM model_profiles")).all()
    finally:
        engine.dispose()
    return dict(rows)


def test_existing_profiles_keep_the_api_they_were_built_on() -> None:
    _alembic("upgrade", _BASE_REVISION)
    _seed_profiles_at_base()

    _alembic("upgrade", _TARGET_REVISION)

    assert _apis() == {
        "openai on its own endpoint": "responses",
        "openai behind a vLLM": "chat",
        "azure": "chat",
        "anthropic": None,
        "anthropic behind a gateway": None,
    }

    _alembic("downgrade", _BASE_REVISION)
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            columns = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'model_profiles'"
                    )
                ).all()
            }
    finally:
        engine.dispose()
    assert "api" not in columns
