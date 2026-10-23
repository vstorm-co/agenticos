"""The 0180 revision: improvement sessions and candidate batches.

Upgraded, a batch can be a session's candidate beside the agent's open batch.
Downgraded, the candidates are deleted first, since the narrower status CHECK
would refuse them, while the open batch and its hunk stay; the session tables
are gone, and upgrading again works over what is left. It owns a database of
its own, as every migration test here does.
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

MIGRATION_DATABASE = f"agenticos_improvement_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BASE_REVISION = "0173_eval_job_pool"
_TARGET_REVISION = "0180_improvement_sessions"


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


def _seed() -> dict[str, uuid.UUID]:
    """An agent with an open batch holding one hunk, and a session with its candidate."""
    ids = {name: uuid.uuid4() for name in ("user", "org", "agent", "dataset", "run")}
    ids["open"], ids["candidate"], ids["hunk"] = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
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
                    "draft_spec, kind) VALUES (:id, :org, :slug, 'Refund desk', 'org', 'draft', "
                    "CAST(:spec AS jsonb), 'agent')"
                ),
                {
                    "id": ids["agent"],
                    "org": ids["org"],
                    "slug": f"refunds-{uuid.uuid4().hex[:8]}",
                    "spec": json.dumps({"name": "Refund desk"}),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO datasets (id, organization_id, visibility, name) "
                    "VALUES (:id, :org, 'org', 'refund questions')"
                ),
                {"id": ids["dataset"], "org": ids["org"]},
            )
            conn.execute(
                text(
                    "INSERT INTO improvement_runs (id, organization_id, agent_id, status, "
                    "iteration, max_iterations, base_draft_hash, dataset_id, dataset_version, "
                    "scoring_hash, window_days, estimate_usd, budget_usd, spent_usd) VALUES "
                    "(:id, :org, :agent, 'running', 1, 3, :hash, :dataset, 1, :hash, 30, "
                    "0.04, 0.04, 0)"
                ),
                {
                    "id": ids["run"],
                    "org": ids["org"],
                    "agent": ids["agent"],
                    "dataset": ids["dataset"],
                    "hash": "a" * 64,
                },
            )
            for batch, status, run in (
                (ids["open"], "open", None),
                (ids["candidate"], "candidate", ids["run"]),
            ):
                conn.execute(
                    text(
                        "INSERT INTO spec_proposal_batches (id, organization_id, agent_id, "
                        "source_started_at, status, expected_effect, improvement_run_id) "
                        "VALUES (:id, :org, :agent, now(), :status, '', :run)"
                    ),
                    {
                        "id": batch,
                        "org": ids["org"],
                        "agent": ids["agent"],
                        "status": status,
                        "run": run,
                    },
                )
            conn.execute(
                text(
                    "INSERT INTO spec_proposal_hunks (id, organization_id, batch_id, position, "
                    "kind, origin, context_before, context_after, old_text, new_text, "
                    "rationale, evidence, evidence_dropped, status) VALUES (:id, :org, :batch, "
                    "0, 'instructions', 'improve', '', '', '', '', '', '[]'::jsonb, 0, "
                    "'pending')"
                ),
                {"id": ids["hunk"], "org": ids["org"], "batch": ids["open"]},
            )
    finally:
        engine.dispose()
    return ids


def test_a_downgrade_deletes_candidates_and_keeps_the_open_batch() -> None:
    _alembic("upgrade", _TARGET_REVISION)
    ids = _seed()

    _alembic("downgrade", _BASE_REVISION)

    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            batches = set(conn.execute(text("SELECT id FROM spec_proposal_batches")).scalars())
            hunks = set(conn.execute(text("SELECT id FROM spec_proposal_hunks")).scalars())
            gone = conn.execute(text("SELECT to_regclass('improvement_runs')")).scalar_one()
    finally:
        engine.dispose()
    assert batches == {ids["open"]}
    assert hunks == {ids["hunk"]}
    assert gone is None

    _alembic("upgrade", _TARGET_REVISION)
