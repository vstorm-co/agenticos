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
    OPEN_STATUSES,
    UNSETTLED_STATUSES,
    ImprovementMode,
    ImprovementRun,
    ImprovementStage,
    ImprovementStatus,
    ImprovementVerdict,
    StopReason,
)

_VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
_MIGRATION = _VERSIONS / "0212_improvement_waiting.py"
_CRITERIA = _VERSIONS / "0342_criterion_verdicts.py"
"""The revision that last changed the verdicts."""
_SEARCH = _VERSIONS / "0356_improvement_search.py"
"""The revision that last changed the stages, the stop reasons and the modes."""


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
    ("path", "constant", "members"),
    [
        (_MIGRATION, "_STATUSES", ImprovementStatus),
        (_SEARCH, "_STAGES", ImprovementStage),
        (_CRITERIA, "_VERDICTS", ImprovementVerdict),
        (_MIGRATION, "_ACTIVE", ACTIVE_STATUSES),
        (_MIGRATION, "_OPEN", OPEN_STATUSES),
        (_MIGRATION, "_UNSETTLED", UNSETTLED_STATUSES),
    ],
)
def test_the_migration_lists_every_value_the_model_allows(
    path: Path, constant: str, members: tuple[StrEnum, ...] | type[StrEnum]
) -> None:
    assert getattr(_migration(path), constant) == _quoted(members)


@pytest.mark.parametrize(
    ("index", "constant"),
    [("uq_improvement_runs_open", "_OPEN"), ("ix_improvement_runs_unsettled", "_UNSETTLED")],
)
def test_the_partial_indexes_cover_the_same_statuses(index: str, constant: str) -> None:
    assert _predicate(index) == f"status IN ({getattr(_migration(), constant)})"


@pytest.mark.parametrize(
    ("path", "name", "pattern", "members"),
    [
        (_MIGRATION, "ck_improvement_run_status", r"status IN \((.+)\)", ImprovementStatus),
        (
            _SEARCH,
            "ck_improvement_run_stop_reason",
            r"stop_reason IS NULL OR stop_reason IN \((.+)\)",
            StopReason,
        ),
        (
            _SEARCH,
            "ck_improvement_run_stage",
            r"stage IS NULL OR stage IN \((.+)\)",
            ImprovementStage,
        ),
        (_SEARCH, "ck_improvement_run_mode", r"mode IN \((.+)\)", ImprovementMode),
    ],
)
def test_the_latest_constraints_match_the_model(
    path: Path, name: str, pattern: str, members: type[StrEnum]
) -> None:
    migration = _migration(path)
    with patch.object(migration, "op") as operations:
        migration.upgrade()
    conditions = {
        call.args[0]: call.args[2]
        for call in operations.create_check_constraint.call_args_list
        if call.args[1] == "improvement_runs"
    }
    matched = re.fullmatch(pattern, conditions[name])
    assert matched is not None
    assert set(re.findall(r"'([^']+)'", matched.group(1))) == {member.value for member in members}


def test_criterion_migration_drops_the_original_postgres_constraint_names():
    from io import StringIO

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def sql(path: Path) -> str:
        output = StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={
                "as_sql": True,
                "output_buffer": output,
                "target_metadata": Base.metadata,
            },
        )
        with Operations.context(context):
            _migration(path).upgrade()
        return output.getvalue()

    original = sql(_VERSIONS / "0180_improvement_sessions.py") + sql(
        _VERSIONS / "0308_skill_improvement_sessions.py"
    )
    current = sql(_CRITERIA)
    drops = re.findall(r"ALTER TABLE (\w+) DROP CONSTRAINT (\w+);", current)
    reported_tables = {
        "improvement_iterations",
        "skill_improvement_iterations",
        "skill_improvement_runs",
    }
    checked = 0
    for table, constraint in drops:
        if table in reported_tables:
            assert f"CONSTRAINT {constraint} CHECK" in original
            checked += 1
    assert checked == 3
