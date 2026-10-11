"""The column-type registry: what each type stores, refuses and lets a query ask."""

import uuid

import pytest

from app.schemas.virtual_table import ColumnDef, OptionDef
from app.services.virtual_tables.types import (
    COLUMN_TYPES,
    MAX_INTEGER,
    MAX_TEXT,
    CellProblem,
    validate_cell,
    validate_default,
    validate_filter,
)


def _column(type_: str, *, nullable: bool = True, options: list[OptionDef] | None = None, **rest):
    return ColumnDef(
        id=uuid.uuid4(), label="c", type=type_, nullable=nullable, options=options or [], **rest
    )


def _select(type_: str = "single_select"):
    live = OptionDef(id=uuid.uuid4(), label="Open")
    old = OptionDef(id=uuid.uuid4(), label="Old", archived=True)
    return _column(type_, options=[live, old]), live, old


def test_every_declared_type_is_registered():
    assert set(COLUMN_TYPES) == {
        "text",
        "long_text",
        "email",
        "url",
        "phone",
        "number",
        "integer",
        "rating",
        "boolean",
        "date",
        "datetime",
        "single_select",
        "multi_select",
        "link",
        "lookup",
        "rollup",
        "formula",
    }


@pytest.mark.parametrize("value", ["  padded  ", "line\nbreak\n", "   ", "", "zażółć 🚀"])
def test_text_is_stored_exactly_as_typed(value):
    assert validate_cell(_column("text"), value) == value


@pytest.mark.parametrize(
    ("type_", "value"),
    [
        ("text", 5),
        ("text", "a\x00b"),
        ("text", "x" * (MAX_TEXT + 1)),
        ("long_text", ["a"]),
        ("number", "5"),
        ("number", True),
        ("number", float("inf")),
        ("integer", 1.5),
        ("integer", True),
        ("integer", "1"),
        ("integer", MAX_INTEGER + 1),
        ("boolean", "true"),
        ("boolean", 1),
        ("date", "2026-1-5"),
        ("date", "2026-02-30"),
        ("date", 20260105),
        ("datetime", "2026-01-05T10:00:00"),
        ("datetime", "yesterday"),
        ("datetime", 5),
    ],
)
def test_a_value_of_the_wrong_type_is_refused_with_a_message(type_, value):
    with pytest.raises(CellProblem):
        validate_cell(_column(type_), value)


def test_numbers_and_whole_numbers_keep_their_value():
    assert validate_cell(_column("number"), 1.25) == 1.25
    assert validate_cell(_column("number"), 3) == 3
    assert validate_cell(_column("integer"), 7) == 7
    assert validate_cell(_column("integer"), 7.0) == 7
    assert validate_cell(_column("boolean"), False) is False


def test_a_date_is_kept_and_a_timestamp_is_normalized_to_utc():
    assert validate_cell(_column("date"), "2026-01-05") == "2026-01-05"
    stored = validate_cell(_column("datetime"), "2026-01-05T10:00:00+02:00")
    assert stored == "2026-01-05T08:00:00.000000+00:00"


def test_null_clears_a_nullable_cell_and_is_refused_on_a_required_one():
    assert validate_cell(_column("text"), None) is None
    with pytest.raises(CellProblem, match="cannot be empty"):
        validate_cell(_column("text", nullable=False), None)


def test_a_select_takes_an_active_option_id_and_refuses_the_rest():
    column, live, old = _select()
    assert validate_cell(column, str(live.id)) == str(live.id)
    for bad in (str(old.id), str(uuid.uuid4()), "not-a-uuid", 4):
        with pytest.raises(CellProblem):
            validate_cell(column, bad)


def test_a_multi_select_takes_a_list_of_distinct_active_options():
    column, live, old = _select("multi_select")
    assert validate_cell(column, [str(live.id)]) == [str(live.id)]
    for bad in ("Open", [str(live.id), str(live.id)], [str(old.id)]):
        with pytest.raises(CellProblem):
            validate_cell(column, bad)


def test_a_default_is_held_to_the_same_rule_as_a_cell():
    assert validate_default(_column("text")) is None
    assert validate_default(_column("integer", default=4)) == 4
    with pytest.raises(CellProblem):
        validate_default(_column("integer", default="four"))


def test_a_filter_operator_the_type_does_not_support_is_refused():
    with pytest.raises(CellProblem, match="supports these operators"):
        validate_filter(_column("boolean"), "lt", True)
    with pytest.raises(CellProblem):
        validate_filter(_column("multi_select"), "eq", "x")


def test_filter_operands_are_validated_against_the_column():
    assert validate_filter(_column("integer"), "gte", 3) == 3
    assert validate_filter(_column("text"), "contains", "ab") == "ab"
    assert validate_filter(_column("text"), "is_null", True) is True
    assert validate_filter(_column("integer"), "in", [1, 2]) == [1, 2]
    for column, op, value in [
        (_column("integer"), "gte", "3"),
        (_column("integer"), "gte", None),
        (_column("text"), "is_null", "yes"),
        (_column("text"), "in", []),
        (_column("text"), "in", "a"),
        (_column("integer"), "in", [1, "2"]),
    ]:
        with pytest.raises(CellProblem):
            validate_filter(column, op, value)


def test_a_filter_may_name_an_archived_option_though_a_write_may_not():
    column, _live, old = _select()
    assert validate_filter(column, "eq", str(old.id)) == str(old.id)
    multi, _live, old = _select("multi_select")
    assert validate_filter(multi, "contains", str(old.id)) == str(old.id)
    with pytest.raises(CellProblem):
        validate_filter(multi, "contains", str(uuid.uuid4()))


OUT_OF_RANGE = ["0001-01-01T00:00:00+02:00", "9999-12-31T23:59:59-02:00"]


@pytest.mark.parametrize("value", OUT_OF_RANGE)
def test_a_timestamp_the_offset_pushes_out_of_range_is_a_refusal_in_every_position(value):
    """Each of a cell, a filter operand and a default is a 422, never an OverflowError."""
    column = _column("datetime")

    with pytest.raises(CellProblem, match="out of range"):
        validate_cell(column, value)
    with pytest.raises(CellProblem, match="out of range"):
        validate_filter(column, "lt", value)
    with pytest.raises(CellProblem, match="out of range"):
        validate_default(_column("datetime", default=value))


def test_the_extreme_timestamps_that_do_fit_are_accepted():
    column = _column("datetime")

    assert validate_cell(column, "0001-01-01T00:00:00Z").startswith("0001-01-01")
    assert validate_cell(column, "9999-12-31T23:59:59+00:00").startswith("9999-12-31")


LONE_SURROGATE = chr(0xD800)


@pytest.mark.parametrize("type_", ["text", "long_text"])
def test_a_lone_surrogate_is_refused_in_a_cell_a_filter_operand_and_a_default(type_):
    """Pydantic accepts it and PostgreSQL then refuses it, which was a 500 in all three."""
    text = "a" + LONE_SURROGATE

    with pytest.raises(CellProblem, match="not valid Unicode"):
        validate_cell(_column(type_), text)
    for op in ("eq", "contains", "starts_with"):
        with pytest.raises(CellProblem, match="not valid Unicode"):
            validate_filter(_column(type_), op, text)
    with pytest.raises(CellProblem, match="not valid Unicode"):
        validate_filter(_column(type_), "in", [text])
    with pytest.raises(CellProblem, match="not valid Unicode"):
        validate_default(_column(type_, default=text))


def test_text_that_merely_looks_unusual_is_still_stored_as_sent():
    paired = "pair " + chr(0x1F680) + " é"

    assert validate_cell(_column("text"), paired) == paired


@pytest.mark.parametrize(
    ("type_", "value"),
    [
        ("email", "ada@example.com"),
        ("email", "first.last+tag@sub.example.co.uk"),
        ("url", "https://example.com/a?b=c"),
        ("url", "http://localhost:8000"),
        ("phone", "+48 600 100 200"),
        ("phone", "(555) 010-9999"),
        ("rating", 1),
        ("rating", 5),
        ("rating", 4.0),
    ],
)
def test_a_contact_or_a_rating_is_kept_as_given(type_, value):
    assert validate_cell(_column(type_), value) == value


@pytest.mark.parametrize(
    ("type_", "value", "says"),
    [
        ("email", "ada.example.com", "email address"),
        ("email", "ada@example", "email address"),
        ("email", "a b@example.com", "email address"),
        ("email", "x" * 250 + "@a.co", "longer"),
        ("email", 5, "Expected text"),
        ("url", "example.com", "http"),
        ("url", "ftp://example.com", "http"),
        ("url", "https://", "http"),
        ("url", "https://exa mple.com", "http"),
        ("phone", "call me", "phone number"),
        ("phone", "+1 23", "at least 5 digits"),
        ("rating", 0, "1 to 5"),
        ("rating", 6, "1 to 5"),
        ("rating", 2.5, "whole number"),
    ],
)
def test_a_contact_or_a_rating_that_is_not_one_is_refused(type_, value, says):
    with pytest.raises(CellProblem, match=says):
        validate_cell(_column(type_), value)


def test_a_contact_is_filtered_as_text_and_a_rating_as_a_number():
    assert validate_filter(_column("email"), "contains", "@example") == "@example"
    assert validate_filter(_column("rating"), "gte", 4) == 4
    with pytest.raises(CellProblem, match="operators"):
        validate_filter(_column("url"), "gt", "https://a.co")


def test_a_link_holds_distinct_record_ids_and_is_filtered_by_one():
    record = str(uuid.uuid4())
    link = _column("link")

    assert validate_cell(link, [record]) == [record]
    assert validate_filter(link, "contains", record) == record
    for refused in ("one", [record, record], [5], [str(uuid.uuid4()) for _ in range(101)]):
        with pytest.raises(CellProblem):
            validate_cell(link, refused)
    with pytest.raises(CellProblem, match="record id"):
        validate_filter(link, "contains", "not-an-id")


@pytest.mark.parametrize("type_", ["lookup", "rollup", "formula"])
def test_a_worked_out_column_is_never_written_or_filtered(type_):
    with pytest.raises(CellProblem, match="worked out"):
        validate_cell(_column(type_), 3)
    with pytest.raises(CellProblem, match="cannot be filtered"):
        validate_filter(_column(type_), "is_null", True)
