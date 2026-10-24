"""The latest improvement migration spells out the values the models derive from their enums.

`alembic check` compares neither CHECK constraints nor partial index predicates, so a
status added to an enum without a migration would only fail on a real database - or,
for the one-session-per-agent index, silently stop guarding.
"""

import importlib.util
import re
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from sqlalchemy import Index

from app.db.base import Base
from app.db.models.improvement import (
    ACTIVE_STATUSES,
    WAITING_STATUSES,
    ImprovementRun,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)

_MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "0186_knowledge_gap_causes.py"


def _migration(path: Path = _MIGRATION) -> ModuleType:
    spec = importlib.util.spec_from_file_location("improvement_sessions_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quoted(members: tuple[StrEnum, ...] | type[StrEnum]) -> str:
    return ", ".join(f"'{member.value}'" for member in members)


def _predicate(name: str) -> str:
    index = next(
        item
        for item in Base.metadata.tables[ImprovementRun.__tablename__].indexes
        if isinstance(item, Index) and item.name == name
    )
    return str(index.dialect_options["postgresql"]["where"])


@pytest.mark.parametrize(
    ("constant", "members"),
    [
        ("_STATUSES", ImprovementStatus),
        ("_STAGES", ImprovementStage),
        ("_VERDICTS", ImprovementVerdict),
        ("_ACTIVE", ACTIVE_STATUSES),
        ("_OPEN", ACTIVE_STATUSES + WAITING_STATUSES),
    ],
)
def test_the_migration_lists_every_value_the_model_allows(
    constant: str, members: tuple[StrEnum, ...] | type[StrEnum]
) -> None:
    assert getattr(_migration(), constant) == _quoted(members)


@pytest.mark.parametrize(
    ("index", "constant"),
    [("uq_improvement_runs_active", "_ACTIVE"), ("ix_improvement_runs_open", "_OPEN")],
)
def test_the_partial_indexes_cover_the_same_statuses(index: str, constant: str) -> None:
    assert _predicate(index) == f"status IN ({getattr(_migration(), constant)})"


def test_the_latest_stop_reason_constraint_matches_the_model() -> None:
    migration = _migration(_MIGRATION.with_name("0197_improvement_rounds.py"))
    with patch.object(migration, "op") as operations:
        migration.upgrade()
    name, table, condition = operations.create_check_constraint.call_args.args
    assert (name, table) == ("ck_improvement_run_stop_reason", "improvement_runs")
    matched = re.fullmatch(r"stop_reason IS NULL OR stop_reason IN \((.+)\)", condition)
    assert matched is not None
    assert set(re.findall(r"'([^']+)'", matched.group(1))) == {
        reason.value for reason in StopReason
    }
