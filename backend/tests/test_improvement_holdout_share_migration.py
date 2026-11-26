"""Migration `0366_improvement_holdout_share`: sessions keep a share, test sets hold out all.

The backfill and the repair of skills' test sets live only in the migration's
SQL, so they run here against real PostgreSQL on a scratch database holding only
the tables the migration reads.
"""

import importlib.util
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, text

from app.core.config import settings

SCRATCH_DATABASE = f"agenticos_holdout_share_test_p{os.getpid()}"
_MIGRATION = (
    Path(__file__).parents[1] / "alembic" / "versions" / "0366_improvement_holdout_share.py"
)
_TABLES = (
    "CREATE TABLE datasets (id uuid PRIMARY KEY, skill_id uuid, "
    "improvement_holdout_share numeric(4,3) NOT NULL)",
    "CREATE TABLE dataset_cases (id uuid PRIMARY KEY, dataset_id uuid NOT NULL, "
    "improvement_partition varchar(16) NOT NULL)",
    "CREATE TABLE improvement_runs (id uuid PRIMARY KEY, dataset_id uuid)",
)


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


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


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("holdout_share_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine() -> Iterator[Engine]:
    maintenance = _url("postgres")
    if not _server_reachable(maintenance):
        pytest.skip("No database reachable - start one with `make docker-db`")
    drop = f'DROP DATABASE IF EXISTS "{SCRATCH_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{SCRATCH_DATABASE}"')
    scratch = create_engine(_url(SCRATCH_DATABASE))
    try:
        with scratch.begin() as connection:
            for table in _TABLES:
                connection.execute(text(table))
        yield scratch
    finally:
        scratch.dispose()
        _outside_a_transaction(maintenance, drop)


def _dataset(connection, *, share: str, skill: bool) -> uuid.UUID:
    dataset_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO datasets VALUES (:id, :skill, :share)"),
        {"id": dataset_id, "skill": uuid.uuid4() if skill else None, "share": share},
    )
    return dataset_id


def _case(connection, dataset_id: uuid.UUID, partition: str) -> uuid.UUID:
    case_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO dataset_cases VALUES (:id, :dataset, :partition)"),
        {"id": case_id, "dataset": dataset_id, "partition": partition},
    )
    return case_id


def _session(connection, dataset_id: uuid.UUID | None) -> uuid.UUID:
    run_id = uuid.uuid4()
    connection.execute(
        text("INSERT INTO improvement_runs VALUES (:id, :dataset)"),
        {"id": run_id, "dataset": dataset_id},
    )
    return run_id


def test_sessions_take_their_datasets_share_and_test_sets_hold_out_every_question(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        ordinary = _dataset(connection, share="0.300", skill=False)
        test_set = _dataset(connection, share="0.200", skill=True)
        learned = _case(connection, ordinary, "train")
        skill_question = _case(connection, test_set, "train")
        running = _session(connection, ordinary)
        orphaned = _session(connection, None)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        shares = dict(
            connection.execute(text("SELECT id, holdout_share FROM improvement_runs")).all()
        )
        datasets = dict(
            connection.execute(text("SELECT id, improvement_holdout_share FROM datasets")).all()
        )
        partitions = dict(
            connection.execute(text("SELECT id, improvement_partition FROM dataset_cases")).all()
        )

    assert shares == {running: Decimal("0.300"), orphaned: Decimal("0.500")}
    assert datasets == {ordinary: Decimal("0.300"), test_set: Decimal("1.000")}
    assert partitions == {learned: "train", skill_question: "holdout"}


def test_downgrade_drops_the_share_and_leaves_test_sets_holding_out(engine: Engine) -> None:
    with engine.begin() as connection:
        test_set = _dataset(connection, share="0.200", skill=True)
        question = _case(connection, test_set, "train")
        _session(connection, test_set)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
            _migration().downgrade()
        columns = {
            row.column_name
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'improvement_runs'"
                )
            )
        }
        partition = connection.scalar(
            text("SELECT improvement_partition FROM dataset_cases WHERE id = :id"),
            {"id": question},
        )

    assert "holdout_share" not in columns
    assert partition == "holdout"
