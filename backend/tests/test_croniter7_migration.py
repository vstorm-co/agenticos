"""Stored six-series cadences remain explicit under the seven-series parser."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest
from croniter import croniter


def _migration() -> ModuleType:
    path = Path(__file__).parents[1] / "alembic/versions/0376_croniter7_schedules.py"
    spec = importlib.util.spec_from_file_location("croniter7_schedules", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("before", "after", "expanded"),
    [
        ("59/15 * * * *", "*/15 * * * *", [0, 15, 30, 45]),
        ("059/15 * * * *", "*/15 * * * *", [0, 15, 30, 45]),
        ("0 23/6 * * *", "0 */6 * * *", [0, 6, 12, 18]),
        ("0 0 31/5 * *", "0 0 */5 * *", [1, 6, 11, 16, 21, 26, 31]),
        ("0 0 * DEC/3 *", "0 0 * */3 *", [1, 4, 7, 10]),
        ("0 0 * * SAT/2", "0 0 * * */2", [0, 2, 4, 6]),
        ("\u0660 \u0660 * DEC/\u0663 *", "0 0 * */3 *", [1, 4, 7, 10]),
    ],
)
def test_maximum_steps_keep_their_actual_old_expansion(
    before: str, after: str, expanded: list[int]
) -> None:
    converted = _migration()._canonical(before, upgrading=True)
    assert converted == after
    index = next(i for i, field in enumerate(before.split()) if "/" in field)
    assert croniter(converted).expanded[index] == expanded


def test_a_stored_weekday_maximum_keeps_its_next_fire_and_run_estimate() -> None:
    converted = _migration()._canonical("* * * * 6/1", upgrading=True)
    start = datetime(2026, 11, 16, 12, tzinfo=UTC)
    schedule = croniter(converted, start)
    assert schedule.get_next(datetime) == datetime(2026, 11, 16, 12, 1, tzinfo=UTC)
    assert croniter("* * * * 6/1", start).get_next(datetime).weekday() == 5


@pytest.mark.parametrize(
    "expression",
    ["0 9 * * 1-5", "0 0 * * 7/1", "0 0 * * 1#2", "0 0 * * L7", "5/15 8-17 * * *"],
)
def test_unaffected_and_special_operators_are_not_reinterpreted(expression: str) -> None:
    assert _migration()._canonical(expression, upgrading=True) == expression


def test_unicode_separators_and_digits_that_were_accepted_become_ascii() -> None:
    assert _migration()._canonical("\u0660\u00a0\u0669\u2003*\t* *", upgrading=True) == "0 9 * * *"


@pytest.mark.parametrize("expression", ["* * * * * *", "0 0 31 2 *", "0 0 * * 1#7", "59/0 * * * *"])
def test_unrepresentable_stored_schedules_refuse_instead_of_guessing(expression: str) -> None:
    with pytest.raises(ValueError):
        _migration()._canonical(expression, upgrading=True)


def test_downgrade_preserves_new_maximum_only_steps_without_restoring_the_old_bug() -> None:
    migration = _migration()
    assert migration._canonical("59/15 23/6 * DEC/3 SAT/2", upgrading=False) == "59 23 * DEC SAT"
    assert migration._canonical("*/15 */6 * */3 */2", upgrading=False) == "*/15 */6 * */3 */2"


def test_an_unfinished_draft_is_left_editable_instead_of_blocking_the_upgrade() -> None:
    migration = _migration()
    assert migration._canonical("59/", upgrading=True, validate=False) == "59/"
    assert migration._canonical("0 0 31 2 *", upgrading=True, validate=False) == "0 0 31 2 *"
    assert migration._canonical("59/15 * * * *", upgrading=True, validate=False) == "*/15 * * * *"
