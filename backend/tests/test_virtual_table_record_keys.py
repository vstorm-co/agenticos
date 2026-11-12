"""Column-label hints must only recommend an unambiguous, writable column."""

from uuid import uuid4

import pytest

from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables.exceptions import InvalidRecordError
from app.services.virtual_tables.records import _merge


def test_an_archived_label_does_not_recommend_an_unwritable_column() -> None:
    archived = ColumnDef(id=uuid4(), label="Retired", type="text", archived=True)
    live = ColumnDef(id=uuid4(), label="Current", type="text")

    with pytest.raises(InvalidRecordError) as error:
        _merge([archived, live], {"Retired": "value"}, None)

    assert "values are keyed by column id" in error.value.message
    assert str(archived.id) not in error.value.message


def test_an_ambiguous_label_does_not_guess_a_column_id() -> None:
    columns = [
        ColumnDef(id=uuid4(), label="Name", type="text"),
        ColumnDef(id=uuid4(), label="NAME", type="text"),
    ]

    with pytest.raises(InvalidRecordError) as error:
        _merge(columns, {"name": "value"}, None)

    assert "values are keyed by column id" in error.value.message
    assert all(str(column.id) not in error.value.message for column in columns)
