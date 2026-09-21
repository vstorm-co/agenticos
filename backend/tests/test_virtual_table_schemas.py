"""The request models are the API contract: what they preserve and what they refuse."""

import pytest
from pydantic import ValidationError

from app.schemas.virtual_table import (
    RecordCreate,
    RecordQuery,
    RecordUpdate,
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
