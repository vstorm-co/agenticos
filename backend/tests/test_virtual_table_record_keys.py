"""What a record write refused for an unknown key tells the caller."""

import uuid

from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables.records import _labels, _not_a_column


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
