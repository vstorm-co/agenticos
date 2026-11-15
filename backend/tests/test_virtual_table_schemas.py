"""The request models are the API contract: what they preserve and what they refuse."""

from uuid import UUID

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.virtual_table import (
    OperationKey,
    RecordCreate,
    RecordLinkChange,
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


LINK_COLUMN = UUID("00000000-0000-4000-8000-000000000001")
TARGET = UUID("00000000-0000-4000-8000-000000000002")


def test_a_link_only_update_preserves_typed_explicit_intent():
    update = RecordUpdate.model_validate(
        {"expected_revision": 2, "link_changes": {str(LINK_COLUMN): {"add": [str(TARGET)]}}}
    )
    assert update.values == {}
    assert update.link_changes[LINK_COLUMN] == RecordLinkChange(add=[TARGET])
    assert update.model_dump(mode="json")["link_changes"] == {
        str(LINK_COLUMN): {"add": [str(TARGET)], "remove": []}
    }


@pytest.mark.parametrize(
    "change",
    [
        {"add": [str(TARGET), str(TARGET)]},
        {"remove": [str(TARGET), str(TARGET)]},
        {"add": [str(TARGET)], "remove": [str(TARGET)]},
        {"add": ["not-a-uuid"]},
        {"add": [str(TARGET)] * 101},
        {"remove": [str(TARGET)] * 101},
        {"replace": []},
    ],
)
def test_an_ambiguous_or_unbounded_link_change_is_refused(change):
    with pytest.raises(ValidationError):
        RecordUpdate.model_validate(
            {"expected_revision": 1, "link_changes": {str(LINK_COLUMN): change}}
        )


@pytest.mark.parametrize(
    "body",
    [
        {"link_changes": {str(LINK_COLUMN): {"add": [str(TARGET)]}}},
        {"expected_revision": 1, "link_changes": {"Items": {"add": [str(TARGET)]}}},
        {
            "expected_revision": 1,
            "values": {str(LINK_COLUMN): []},
            "link_changes": {str(LINK_COLUMN): {"add": [str(TARGET)]}},
        },
    ],
)
def test_link_changes_require_a_revision_and_one_unambiguous_column_id(body):
    with pytest.raises(ValidationError):
        RecordUpdate.model_validate(body)


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
