"""Column-label hints must only recommend an unambiguous, writable column."""

import uuid
from uuid import uuid4

import pytest

from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables.exceptions import InvalidRecordError
from app.services.virtual_tables.records import _labels, _merge, _not_a_column


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


def _column(label: str, *, archived: bool = False) -> ColumnDef:
    return ColumnDef(id=uuid.uuid4(), label=label, type="text", archived=archived)


def test_an_archived_columns_label_is_not_offered_as_the_id_to_use() -> None:
    """An archived column cannot be written, so naming its id would only lead the
    caller into a second refusal."""
    region = _column("Region", archived=True)
    customer = _column("Customer")

    labels = _labels([region, customer])

    assert "Values are keyed by column id" in _not_a_column(labels, "customer")
    assert str(customer.id) in _not_a_column(labels, "customer")
    assert _not_a_column(labels, "region") == (
        "That is not a column of this table - values are keyed by column id"
    )


def test_a_computed_columns_label_is_not_offered_as_the_id_to_use() -> None:
    """A lookup, rollup or formula is never written, so its id would be a second refusal too."""
    total = ColumnDef(id=uuid.uuid4(), label="Total", type="formula")

    assert _not_a_column(_labels([total]), "total") == (
        "That is not a column of this table - values are keyed by column id"
    )
