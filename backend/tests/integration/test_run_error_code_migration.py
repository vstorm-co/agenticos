"""The 0369 revision, exercised on sessions and requests that already failed.

`tests/test_migrations.py` runs the chain on an empty database, where no row holds a
sentence to read. This writes failed Improve sessions and assistant requests as the
code before the revision did, upgrades, and asserts that each sentence the backend
writes word for word - or with one count in it - got its code and that count, and
that a refusal's own message got none; then downgrades and asserts the columns are gone.

It owns a database of its own - created here, dropped when the module is done -
for the reason `test_migrations.py` does.
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

MIGRATION_DATABASE = f"agenticos_run_error_code_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BEFORE = "0364_merge_routine_and_kb"
_REVISION = "0369_run_error_code"

type Coded = tuple[str | None, dict[str, int] | None]

_SESSIONS: dict[str, Coded] = {
    "Add 3 more held-out test questions to measure a change": ("too_few_held_out", {"missing": 3}),
    "No rated chat runs or training failures are available yet": ("no_evidence", None),
    "A search needs at least 10 training questions for this attempt": (
        "search_too_few_training",
        {"minimum": 10},
    ),
    "Knowledge step not found": (None, None),
    "Add 12345678901 more held-out test questions to measure a change": (None, None),
}

_REQUESTS: dict[str, Coded] = {
    "Whoever started this may no longer read runs.": ("no_runs_view", None),
    "An evidence source was erased while the assistant worked. Start again with current "
    "evidence.": ("evidence_erased", None),
    "Whoever started this may no longer edit the agent.": ("no_edit_agent", None),
    "The agent is gone.": ("agent_gone", None),
    "The agent has no published version to compare with.": ("no_published_version", None),
    "The skill is gone.": ("skill_gone", None),
    "Whoever started this may no longer edit the skill.": ("no_edit_skill", None),
    "The improvement session moved on.": ("session_moved_on", None),
    "The assistant did not answer every conflict; settle them at Changes.": (
        "conflicts_unanswered",
        None,
    ),
    "The improvement session stopped.": ("session_stopped", None),
    "The context file is gone.": ("context_gone", None),
    "Whoever started this may no longer edit the context file.": ("no_edit_context", None),
    "No run in this window is known to have used the skill. 4 rated-down or failed runs are "
    "from before uses were recorded, so whether they used it is unknown.": (
        "unknown_skill_use",
        {"runs": 4},
    ),
    "Nothing to learn from yet: no run in this window was rated or failed. Widen the window, "
    "or come back once people have rated some answers.": ("no_evidence", None),
    "The API key that started this was revoked or no longer exists, so it was stopped.": (
        "key_revoked",
        None,
    ),
    "Whoever started this is no longer a member.": ("not_a_member", None),
    "The assistant stopped unexpectedly. Try again.": ("unexpected", None),
    "The assistant stopped without finishing. Try again.": ("stalled", None),
    "The request was cancelled before it started. Try again.": ("withdrawn", None),
    "'Improver' answered in a form that could not be read.": (None, None),
}


_READS = {
    table: f"SELECT error, error_code, error_params::text FROM {table}"  # noqa: S608
    for table in ("improvement_runs", "authoring_requests")
}


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


def _write_failures() -> None:
    """One agent's failed sessions and requests, as rows held before the revision."""
    user, org = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, 'owner@example.com', true, false)"
                ),
                {"id": user},
            )
            conn.execute(
                text(
                    "INSERT INTO organizations (id, name, slug, is_personal, created_by_user_id) "
                    "VALUES (:id, 'Acme', 'acme', false, :user)"
                ),
                {"id": org, "user": user},
            )
            agents = [uuid.uuid4() for _ in _SESSIONS]
            for number, agent in enumerate(agents):
                conn.execute(
                    text(
                        "INSERT INTO agents (id, organization_id, visibility, slug, name, status) "
                        "VALUES (:id, :org, 'org', :slug, 'Support', 'draft')"
                    ),
                    {"id": agent, "org": org, "slug": f"support-{number}"},
                )
            # A failed session is still open, and an agent has one open session at a time.
            for agent, error in zip(agents, _SESSIONS, strict=True):
                conn.execute(
                    text(
                        "INSERT INTO improvement_runs (id, organization_id, agent_id, status, "
                        "iteration, max_iterations, base_draft_hash, dataset_id, "
                        "dataset_version, scoring_hash, window_days, estimate_usd, budget_usd, "
                        "spent_usd, error) VALUES (:id, :org, :agent, 'failed', 1, 1, 'h', "
                        ":dataset, 1, 'h', 30, 0, 0, 0, :error)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "org": org,
                        "agent": agent,
                        "dataset": uuid.uuid4(),
                        "error": error,
                    },
                )
            for error in _REQUESTS:
                conn.execute(
                    text(
                        "INSERT INTO authoring_requests (id, organization_id, kind, target, "
                        "agent_id, status, estimate_usd, cost_usd, window_days, evidence, error) "
                        "VALUES (:id, :org, 'improve', 'agent', :agent, 'failed', 0, 0, 30, "
                        "'{}', :error)"
                    ),
                    {"id": uuid.uuid4(), "org": org, "agent": agents[0], "error": error},
                )
    finally:
        engine.dispose()


def _coded(table: str) -> dict[str, Coded]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(_READS[table])).tuples()
            return {
                error: (code, None if params is None else json.loads(params))
                for error, code, params in rows
            }
    finally:
        engine.dispose()


def _columns(table: str) -> set[str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :table"
                    ),
                    {"table": table},
                ).scalars()
            )
    finally:
        engine.dispose()


def test_a_failure_written_before_codes_gets_the_code_its_sentence_names() -> None:
    """The console words a coded failure in the reader's language and shows an
    uncoded one as stored, so a sentence matched loosely would be mistranslated."""
    _alembic("upgrade", _BEFORE)
    _write_failures()

    _alembic("upgrade", _REVISION)
    assert _coded("improvement_runs") == _SESSIONS
    assert _coded("authoring_requests") == _REQUESTS

    _alembic("downgrade", _BEFORE)
    for table in ("improvement_runs", "authoring_requests"):
        assert {"error", "error_code", "error_params"} & _columns(table) == {"error"}

    _alembic("upgrade", "head")
