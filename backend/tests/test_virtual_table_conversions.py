"""Which column types may become which, and the value each becomes."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.schemas.virtual_table import CellValue, ColumnDef, ColumnTypeName, OptionDef
from app.services.virtual_tables.conversions import convert, convertible, option_labels
from app.services.virtual_tables.types import CellProblem

# Fixed, not drawn: a parameter holding one names its test, which every xdist
# worker must collect alike.
OPEN = UUID("00000000-0000-4000-8000-000000000001")
DONE = UUID("00000000-0000-4000-8000-000000000002")
GONE = UUID("00000000-0000-4000-8000-000000000003")
OPTIONS = [
    OptionDef(id=OPEN, label="Open"),
    OptionDef(id=DONE, label="Done"),
    OptionDef(id=GONE, label="Gone", archived=True),
]


def column(type_: ColumnTypeName, **rest: Any) -> ColumnDef:
    options = rest.pop("options", OPTIONS if type_ in ("single_select", "multi_select") else [])
    return ColumnDef(id=uuid4(), label="C", type=type_, options=options, **rest)


def becomes(value: CellValue, old: ColumnTypeName, new: ColumnTypeName) -> CellValue:
    return convert(value, column(old), column(new))


def test_only_changes_a_value_survives_are_offered():
    assert convertible("text", "integer")
    assert convertible("integer", "number")
    assert convertible("single_select", "multi_select")
    assert not convertible("date", "integer")
    assert not convertible("boolean", "date")
    assert not convertible("number", "single_select")


@pytest.mark.parametrize(
    ("value", "new", "expected"),
    [
        ("42", "integer", 42),
        (" -7 ", "integer", -7),
        ("3.5", "number", 3.5),
        ("4", "number", 4),
        ("1e3", "number", 1000.0),
        ("Yes", "boolean", True),
        ("0", "boolean", False),
        ("2026-10-01", "date", "2026-10-01"),
        ("2026-10-01T09:30:00", "datetime", "2026-10-01T09:30:00.000000+00:00"),
        ("2026-10-01T09:30:00+02:00", "datetime", "2026-10-01T07:30:00.000000+00:00"),
        ("Done", "single_select", str(DONE)),
        ("a note", "long_text", "a note"),
        ("   ", "integer", None),
    ],
)
def test_text_becomes_what_it_says(value: str, new: ColumnTypeName, expected: CellValue):
    assert becomes(value, "text", new) == expected


@pytest.mark.parametrize(
    ("value", "new"),
    [
        ("forty", "integer"),
        ("4.5", "integer"),
        ("4,5", "number"),
        ("maybe", "boolean"),
        ("01/10/2026", "date"),
        ("tomorrow", "datetime"),
        ("Unknown", "single_select"),
        # An archived option is not one a value can become.
        ("Gone", "single_select"),
    ],
)
def test_text_that_says_nothing_of_the_kind_is_refused(value: str, new: ColumnTypeName):
    with pytest.raises(CellProblem):
        becomes(value, "text", new)


def test_long_text_becomes_text_only_when_it_fits():
    assert becomes("short", "long_text", "text") == "short"
    with pytest.raises(CellProblem):
        becomes("x" * 1001, "long_text", "text")


@pytest.mark.parametrize(
    ("value", "old", "expected"),
    [
        (3.0, "number", "3"),
        (2.5, "number", "2.5"),
        (7, "integer", "7"),
        (True, "boolean", "true"),
        (False, "boolean", "false"),
        ("2026-10-01", "date", "2026-10-01"),
        (str(OPEN), "single_select", "Open"),
        ([str(OPEN), str(GONE)], "multi_select", "Open, Gone"),
    ],
)
def test_anything_becomes_text_as_it_reads(value: CellValue, old: ColumnTypeName, expected: str):
    assert becomes(value, old, "text") == expected


def test_a_choice_naming_no_option_does_not_become_text():
    with pytest.raises(CellProblem):
        becomes(str(uuid4()), "single_select", "text")
    # A multi-select holding something other than a list reads as no choices.
    assert becomes("odd", "multi_select", "text") == ""


def test_numbers_become_each_other_where_they_can():
    assert becomes(5, "integer", "number") == 5
    assert becomes(3.0, "number", "integer") == 3
    with pytest.raises(CellProblem):
        becomes(3.5, "number", "integer")


def test_a_date_becomes_its_midnight():
    assert becomes("2026-10-01", "date", "datetime") == "2026-10-01T00:00:00.000000+00:00"


def test_one_choice_becomes_several_and_back_when_it_was_one():
    assert becomes(str(OPEN), "single_select", "multi_select") == [str(OPEN)]
    assert becomes([str(DONE)], "multi_select", "single_select") == str(DONE)
    assert becomes([], "multi_select", "single_select") is None
    assert becomes("odd", "multi_select", "single_select") is None
    with pytest.raises(CellProblem):
        becomes([str(OPEN), str(DONE)], "multi_select", "single_select")


def test_no_value_stays_no_value():
    assert becomes(None, "text", "integer") is None


def test_the_choices_text_becomes_are_its_distinct_values_in_order():
    assert option_labels(["b", " a ", "", "b", None, 3, "a"]) == ["b", "a"]
