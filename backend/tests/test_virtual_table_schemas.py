"""The request models are the API contract: what they preserve and what they refuse."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.virtual_table import (
    OperationKey,
    RecordCreate,
    RecordQuery,
    RecordUpdate,
    RecordUpsert,
    TableCreate,
)


def test_cell_text_is_not_trimmed_but_a_label_is():
    record = RecordCreate(values={"a": "  padded \n"})
    table = TableCreate(name="  orders  ")
    assert record.values == {"a": "  padded \n"}
    assert table.name == "orders"


def test_a_label_of_only_spaces_is_refused():
    with pytest.raises(ValidationError):
        TableCreate(name="   ")


@pytest.mark.security
def test_an_unknown_request_field_is_refused_rather_than_ignored():
    """A misspelled `expected_revison` must not become a write with no concurrency check."""
    with pytest.raises(ValidationError):
        RecordUpdate.model_validate({"expected_revison": 1, "values": {}})


@pytest.mark.security
def test_an_update_cannot_omit_its_expected_revision():
    with pytest.raises(ValidationError):
        RecordUpdate.model_validate({"values": {}})


def test_a_query_is_bounded():
    assert RecordQuery().limit == 50
    for bad in ({"limit": 0}, {"limit": 101}, {"skip": -1}, {"skip": 10_001}):
        with pytest.raises(ValidationError):
            RecordQuery.model_validate(bad)
    with pytest.raises(ValidationError):
        RecordQuery.model_validate({"filters": [{"column_id": "not-a-uuid", "op": "eq"}]})


SURROGATE = chr(0xD800)


@pytest.mark.parametrize(
    "build",
    [
        lambda bad: TableCreate(name=bad),
        lambda bad: TableCreate(name="ok", description=bad),
        lambda bad: TableCreate(name="ok", columns=[{"label": bad, "type": "text"}]),
        lambda bad: TableCreate(
            name="ok",
            columns=[{"label": "Pick", "type": "single_select", "options": [{"label": bad}]}],
        ),
        lambda bad: RecordCreate(external_id=bad, values={}),
        lambda bad: RecordCreate(values={bad: 1}),
        lambda bad: RecordUpdate(expected_revision=1, values={bad: 1}),
        lambda bad: RecordUpsert(values={bad: 1}),
    ],
)
def test_a_lone_surrogate_is_refused_wherever_a_caller_string_reaches_the_database(build):
    with pytest.raises(ValidationError):
        build("a" + SURROGATE)


def test_a_values_key_is_bounded_because_an_unknown_one_is_echoed_back():
    with pytest.raises(ValidationError):
        RecordCreate(values={"k" * 65: 1})
    assert RecordCreate(values={"k" * 64: 1}).values


def test_the_operation_key_type_refuses_a_surrogate_and_a_line_break():
    adapter = TypeAdapter(OperationKey)

    for bad in ("a" + SURROGATE, "a\nb"):
        with pytest.raises(ValidationError):
            adapter.validate_python(bad)
