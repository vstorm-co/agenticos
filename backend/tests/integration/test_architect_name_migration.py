"""The 0120 revision: an assistant installed before the rename is the Architect.

Only an organization's assistant under one of the two names it was installed
with moves, in its row and its draft; an agent that merely shares the name, and
an assistant somebody renamed, are left as they are. The downgrade puts the old
names back. It owns a database of its own, as every migration test here does.
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

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_architect_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0119_mcp_server_alerts"
_TARGET_REVISION = "0120_architect_name"


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


def _seed() -> dict[str, uuid.UUID]:
    """Two organizations at 0119: assistants under each installed name, an
    assistant an administrator renamed, and an ordinary agent called AI Architect."""
    ids = {key: uuid.uuid4() for key in ("plain", "fallback", "renamed", "lookalike")}
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            user_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, :email, true, false)"
                ),
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            )
            rows = (
                ("plain", "AI Architect", True),
                ("fallback", "AI Architect (AgenticOS)", True),
                ("renamed", "Helpdesk", True),
                ("lookalike", "AI Architect", False),
            )
            for key, name, assistant in rows:
                org_id = uuid.uuid4()
                conn.execute(
                    text(
                        "INSERT INTO organizations (id, name, slug, created_by_user_id, "
                        "is_personal, chat_may_waive_approvals) "
                        "VALUES (:id, 'Acme', :slug, :owner, false, false)"
                    ),
                    {"id": org_id, "slug": f"acme-{uuid.uuid4().hex[:8]}", "owner": user_id},
                )
                conn.execute(
                    text(
                        "INSERT INTO agents (id, organization_id, slug, name, visibility, "
                        "status, draft_spec) VALUES (:id, :org, :slug, :name, 'org', "
                        "'draft', CAST(:spec AS jsonb))"
                    ),
                    {
                        "id": ids[key],
                        "org": org_id,
                        "slug": f"agent-{uuid.uuid4().hex[:8]}",
                        "name": name,
                        "spec": json.dumps({"name": name, "instructions": "Help."}),
                    },
                )
                if assistant:
                    conn.execute(
                        text(
                            "INSERT INTO organization_assistants (organization_id, agent_id) "
                            "VALUES (:org, :agent)"
                        ),
                        {"org": org_id, "agent": ids[key]},
                    )
    finally:
        engine.dispose()
    return ids


def _names(ids: dict[str, uuid.UUID]) -> dict[str, tuple[str, str]]:
    """Each agent's row name and draft name, by key."""
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name, draft_spec->>'name' FROM agents WHERE id = ANY(:ids)"),
                {"ids": list(ids.values())},
            ).all()
    finally:
        engine.dispose()
    by_id = {row[0]: (row[1], row[2]) for row in rows}
    return {key: by_id[agent_id] for key, agent_id in ids.items()}


def test_only_an_assistant_under_an_installed_name_becomes_the_architect() -> None:
    _alembic("upgrade", _BASE_REVISION)
    ids = _seed()

    _alembic("upgrade", _TARGET_REVISION)

    assert _names(ids) == {
        "plain": ("Architect", "Architect"),
        "fallback": ("Architect (AgenticOS)", "Architect (AgenticOS)"),
        "renamed": ("Helpdesk", "Helpdesk"),
        "lookalike": ("AI Architect", "AI Architect"),
    }

    _alembic("downgrade", _BASE_REVISION)

    assert _names(ids) == {
        "plain": ("AI Architect", "AI Architect"),
        "fallback": ("AI Architect (AgenticOS)", "AI Architect (AgenticOS)"),
        "renamed": ("Helpdesk", "Helpdesk"),
        "lookalike": ("AI Architect", "AI Architect"),
    }
