"""Migration `0080_audit_checkpoints`: the backfill and the append-only trigger.

Two things live only in the migration, not the models, so an integration suite
built from `create_all` cannot reach them: the checkpoint backfilled from a chain
that predates it, and the trigger that forbids a checkpoint moving backwards or
being deleted. This drives the real migration against a database of its own -
upgrade to the revision before checkpoints, insert a chain the old way, upgrade
through `0080` - and then asserts both (#1648). It creates and drops that database
itself, as `tests/test_migrations.py` and `tests/test_audit_chain_backfill.py` do.
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

CHECKPOINT_DATABASE = f"agenticos_audit_checkpoint_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_REVISION_BEFORE_CHECKPOINTS = "0079_audit_hash_chain"

_ORG_A = uuid.uuid4()
_ORG_B = uuid.uuid4()
# (organization_id, seq); the head of each chain is its highest seq. A deployment
# (null-organization) chain is in here too, so the backfill's NULLS-NOT-DISTINCT
# grouping is exercised.
_ROWS = [
    (_ORG_A, 1),
    (_ORG_B, 2),
    (None, 3),
    (_ORG_A, 4),
    (_ORG_B, 5),
    (_ORG_A, 6),
    (None, 7),
]
_EXPECTED = {
    _ORG_A: {"max_seq": 6, "entry_count": 3},
    _ORG_B: {"max_seq": 5, "entry_count": 2},
    None: {"max_seq": 7, "entry_count": 2},
}


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": CHECKPOINT_DATABASE},
        timeout=120,
    )


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


def _seq_hash(seq: int) -> str:
    """A distinct 64-hex entry_hash per row, so head_entry_hash is checkable."""
    return f"{seq:064x}"


def _insert_pre_checkpoint_chain() -> None:
    engine = create_engine(_url(CHECKPOINT_DATABASE))
    statement = text(
        "INSERT INTO app_admin_audit_logs "
        "(id, actor_user_id, organization_id, action, created_at, seq, prev_hash, entry_hash) "
        "VALUES (:id, :actor, :org, :action, now(), :seq, :prev, :entry)"
    )
    try:
        with engine.begin() as connection:
            for org, seq in _ROWS:
                connection.execute(
                    statement,
                    {
                        "id": uuid.uuid4(),
                        "actor": uuid.uuid4(),
                        "org": org,
                        "action": "agent.published",
                        "seq": seq,
                        "prev": None,
                        "entry": _seq_hash(seq),
                    },
                )
    finally:
        engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _checkpoint_database() -> Iterator[None]:
    maintenance = _url(_MAINTENANCE_DATABASE)
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{CHECKPOINT_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{CHECKPOINT_DATABASE}"')
    try:
        before = _alembic("upgrade", _REVISION_BEFORE_CHECKPOINTS)
        assert before.returncode == 0, (
            f"upgrade to {_REVISION_BEFORE_CHECKPOINTS} failed:\n{before.stderr}"
        )
        _insert_pre_checkpoint_chain()
        after = _alembic("upgrade", "head")
        assert after.returncode == 0, f"upgrade through 0080 failed:\n{after.stderr}"
        yield
    finally:
        _outside_a_transaction(maintenance, drop)


def test_the_backfill_records_each_chains_high_water_mark() -> None:
    engine = create_engine(_url(CHECKPOINT_DATABASE))
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT organization_id, max_seq, entry_count, head_entry_hash "
                    "FROM app_admin_audit_checkpoints"
                )
            ).all()
    finally:
        engine.dispose()

    by_org = {row.organization_id: row for row in rows}
    assert set(by_org) == set(_EXPECTED)
    for org, expected in _EXPECTED.items():
        assert by_org[org].max_seq == expected["max_seq"]
        assert by_org[org].entry_count == expected["entry_count"]
        assert by_org[org].head_entry_hash == _seq_hash(expected["max_seq"])


def test_the_guard_forbids_a_checkpoint_moving_backwards_or_being_deleted() -> None:
    from sqlalchemy.exc import InternalError, ProgrammingError

    engine = create_engine(_url(CHECKPOINT_DATABASE))
    try:
        # Moving the mark backwards is refused.
        with pytest.raises((InternalError, ProgrammingError)), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE app_admin_audit_checkpoints SET max_seq = max_seq - 1 "
                    "WHERE organization_id = :org"
                ),
                {"org": _ORG_A},
            )

        # Deleting the mark is refused.
        with pytest.raises((InternalError, ProgrammingError)), engine.begin() as connection:
            connection.execute(
                text("DELETE FROM app_admin_audit_checkpoints WHERE organization_id = :org"),
                {"org": _ORG_A},
            )

        # Advancing it is allowed - which is all `record_audit` ever does.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE app_admin_audit_checkpoints "
                    "SET max_seq = max_seq + 1, entry_count = entry_count + 1 "
                    "WHERE organization_id = :org"
                ),
                {"org": _ORG_A},
            )
            advanced = connection.execute(
                text(
                    "SELECT max_seq FROM app_admin_audit_checkpoints WHERE organization_id = :org"
                ),
                {"org": _ORG_A},
            ).scalar_one()
        assert advanced == _EXPECTED[_ORG_A]["max_seq"] + 1
    finally:
        engine.dispose()
