"""Saved presentation validates independently of record values and old views."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.table_view import TableDisplay, TableViewConfig


def test_old_views_get_compatible_display_defaults():
    assert TableViewConfig.model_validate({"filters": []}).display == TableDisplay()


@pytest.mark.parametrize(
    "value",
    [
        {"column_order": ["created_at", "created_at"]},
        {"column_order": ["not-a-column"]},
        {"hidden_system_columns": ["password"]},
        {"hidden_system_columns": ["created_by", "created_by"]},
        {"date_format": "invalid"},
        {"time_format": "invalid"},
    ],
)
def test_invalid_presentation_is_refused(value):
    with pytest.raises(ValidationError):
        TableDisplay.model_validate(value)


def test_column_keys_accept_uuid_and_system_fields():
    column_id = uuid.uuid4()
    result = TableDisplay.model_validate({"column_order": [str(column_id), "created_at"]})
    assert result.column_order == [column_id, "created_at"]
