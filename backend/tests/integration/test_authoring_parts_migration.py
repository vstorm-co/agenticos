"""The 0171 revision: spec field hunks, context requests and context proposals.

Upgraded, a hunk can change a field of the spec and the assistant can be asked
about a context file. Downgraded, what the narrower checks would refuse is
deleted first - spec field hunks, context requests - while an instruction hunk
stays, and upgrading again works over what is left. It owns a database of its
own, as every migration test here does.
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

MIGRATION_DATABASE = f"agenticos_authoring_parts_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0170_promotion_gate"
_TARGET_REVISION = "0171_authoring_agent_parts"


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
    """A batch with an instruction hunk and a spec field hunk, and a context request."""
    ids = {name: uuid.uuid4() for name in ("user", "org", "agent", "context", "batch")}
    ids["kept"], ids["field"], ids["request"] = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, :email, true, false)"
                ),
                {"id": ids["user"], "email": f"{uuid.uuid4().hex}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, created_by_user_id, "
                    "is_personal, chat_may_waive_approvals) "
                    "VALUES (:id, 'Acme', :slug, :owner, false, false)"
                ),
                {"id": ids["org"], "slug": f"acme-{uuid.uuid4().hex[:8]}", "owner": ids["user"]},
            )
            conn.execute(
                text(
                    "INSERT INTO agents (id, organization_id, slug, name, visibility, status, "
                    "draft_spec, kind) VALUES (:id, :org, :slug, 'Clerk', 'org', 'draft', "
                    "CAST(:spec AS jsonb), 'agent')"
                ),
                {
                    "id": ids["agent"],
                    "org": ids["org"],
                    "slug": f"clerk-{uuid.uuid4().hex[:8]}",
                    "spec": json.dumps({"name": "Clerk"}),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO context_files (id, organization_id, visibility, name, content, "
                    "format, mode, enabled) VALUES (:id, :org, 'org', 'policy', 'x', 'md', "
                    "'inject', true)"
                ),
                {"id": ids["context"], "org": ids["org"]},
            )
            conn.execute(
                text(
                    "INSERT INTO authoring_requests (id, organization_id, kind, target, "
                    "context_id, status, estimate_usd, cost_usd, window_days, evidence) "
                    "VALUES (:id, :org, 'improve', 'context', :context, 'completed', 0, 0, 30, "
                    "'{}'::jsonb)"
                ),
                {"id": ids["request"], "org": ids["org"], "context": ids["context"]},
            )
            conn.execute(
                text(
                    "INSERT INTO context_proposals (id, organization_id, context_id, content, "
                    "status, rationale, evidence, evidence_dropped, expected_effect) VALUES "
                    "(:id, :org, :context, 'y', 'pending', '', '[]'::jsonb, 0, '')"
                ),
                {"id": uuid.uuid4(), "org": ids["org"], "context": ids["context"]},
            )
            conn.execute(
                text(
                    "INSERT INTO spec_proposal_batches (id, organization_id, agent_id, "
                    "source_started_at, status, expected_effect) VALUES "
                    "(:id, :org, :agent, now(), 'open', '')"
                ),
                {"id": ids["batch"], "org": ids["org"], "agent": ids["agent"]},
            )
            for hunk, kind, path in (
                (ids["kept"], "instructions", None),
                (ids["field"], "spec_field", "max_steps"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO spec_proposal_hunks (id, organization_id, batch_id, "
                        "position, kind, origin, context_before, context_after, old_text, "
                        "new_text, rationale, evidence, evidence_dropped, status, path, op, "
                        "base_value, new_value) VALUES (:id, :org, :batch, 0, :kind, 'improve', "
                        "'', '', '', '', '', '[]'::jsonb, 0, 'pending', :path, :op, "
                        "CAST(:base AS jsonb), CAST(:new AS jsonb))"
                    ),
                    {
                        "id": hunk,
                        "org": ids["org"],
                        "batch": ids["batch"],
                        "kind": kind,
                        "path": path,
                        "op": None if path is None else "set",
                        "base": None if path is None else "10",
                        "new": None if path is None else "20",
                    },
                )
    finally:
        engine.dispose()
    return ids


def test_a_downgrade_deletes_what_the_narrower_checks_refuse() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    ids = _seed()

    _alembic("downgrade", _BASE_REVISION)

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            hunks = set(conn.execute(text("SELECT id FROM spec_proposal_hunks")).scalars())
            requests = conn.execute(
                text("SELECT count(*) FROM authoring_requests WHERE id = :id"),
                {"id": ids["request"]},
            ).scalar_one()
            gone = conn.execute(text("SELECT to_regclass('context_proposals')")).scalar_one()
    finally:
        engine.dispose()
    assert hunks == {ids["kept"]}
    assert requests == 0
    assert gone is None

    _alembic("upgrade", _TARGET_REVISION)
