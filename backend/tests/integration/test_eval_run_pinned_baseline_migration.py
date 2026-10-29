"""The 0184 revision, exercised on eval runs read before their baseline was kept.

`tests/test_migrations.py` runs the chain on an empty database, where there is
no run to pin. This writes runs as the code before the revision left them -
some with a comparison kept in `outcome` - upgrades, and asserts only the ones
compared with an earlier run that still exists were pinned to it.

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

MIGRATION_DATABASE = f"agenticos_pinned_baseline_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_BEFORE = "0176_eval_case_fault"
_REVISION = "0184_eval_run_pinned_baseline"


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


ORG = uuid.uuid4()


def _run(*, outcome: dict[str, object] | None = None, baseline_arm: bool = False) -> uuid.UUID:
    """A run as the code before the revision wrote it; its foreign keys point nowhere,
    which the session lets pass so only the columns the revision reads are written."""
    run_id = uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SET session_replication_role = replica")
            conn.execute(
                text(
                    "INSERT INTO eval_runs (id, organization_id, agent_id, dataset_id, "
                    "dataset_version_id, status, purpose, paired, from_recordings, live_reads, "
                    "reruns, scoring, scoring_hash, estimate_usd, rerun_ceiling_usd, "
                    "routed_to_review, routed_replacing, outcome) VALUES (:id, :org, :agent, "
                    ":dataset, :version, 'completed', 'manual', false, false, false, 2, '{}', "
                    "'hash', 0, 0, 0, 0, CAST(:outcome AS jsonb))"
                ),
                {
                    "id": run_id,
                    "org": ORG,
                    "agent": uuid.uuid4(),
                    "dataset": uuid.uuid4(),
                    "version": uuid.uuid4(),
                    "outcome": None if outcome is None else json.dumps(outcome),
                },
            )
            if baseline_arm:
                conn.execute(
                    text(
                        "INSERT INTO eval_run_arms (id, organization_id, eval_run_id, role, "
                        "position, source, spec_hash, model_label) VALUES (:id, :org, :run, "
                        "'baseline', 1, 'version', 'hash', 'gpt-test')"
                    ),
                    {"id": uuid.uuid4(), "org": ORG, "run": run_id},
                )
    finally:
        engine.dispose()
    return run_id


def _baselines() -> dict[uuid.UUID, uuid.UUID | None]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT id, baseline_run_id FROM eval_runs")).tuples().all()
    finally:
        engine.dispose()
    return dict(rows)


def _compared_with(run_id: uuid.UUID) -> dict[str, object]:
    return {"baseline": {"run_id": str(run_id)}}


def test_a_run_read_before_its_baseline_was_kept_is_pinned_to_what_it_said() -> None:
    _alembic("upgrade", _BEFORE)
    earlier = _run()
    read = _run(outcome=_compared_with(earlier))
    paired = _run(outcome=_compared_with(earlier), baseline_arm=True)
    gone = _run(outcome=_compared_with(uuid.uuid4()))
    first = _run(outcome={"baseline": None})
    never_read = _run()

    _alembic("upgrade", _REVISION)

    assert _baselines() == {
        earlier: None,
        read: earlier,
        paired: None,
        gone: None,
        first: None,
        never_read: None,
    }
    _alembic("downgrade", _BEFORE)
    assert _baselines()[read] == earlier
    _alembic("upgrade", "head")
