"""A select's choice as an agent or a workflow step names it: by its label, both ways."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.schemas.virtual_table import (
    ColumnDef,
    OptionDef,
    RecordFilter,
    RecordRead,
    TableRead,
)
from app.services.virtual_tables.presentation import column_keyed, filters_by_label, labelled
from app.services.virtual_tables.types import COLUMN_TYPES, CellProblem

WON = UUID("00000000-0000-4000-8000-000000000001")
LOST = UUID("00000000-0000-4000-8000-000000000002")
OLD = UUID("00000000-0000-4000-8000-000000000003")
OPTIONS = [
    OptionDef(id=WON, label="Won"),
    OptionDef(id=LOST, label="Lost"),
    OptionDef(id=OLD, label="Old", archived=True),
]
STAGE = ColumnDef(
    id=UUID("00000000-0000-4000-8000-0000000000a1"),
    label="Stage",
    type="single_select",
    options=OPTIONS,
)
TAGS = ColumnDef(
    id=UUID("00000000-0000-4000-8000-0000000000a2"),
    label="Tags",
    type="multi_select",
    options=OPTIONS,
)
NAME = ColumnDef(id=UUID("00000000-0000-4000-8000-0000000000a3"), label="Name", type="text")
TABLE = TableRead(
    id=UUID("00000000-0000-4000-8000-0000000000b1"),
    name="Leads",
    visibility="private",
    schema_version=1,
    created_at=datetime(2026, 10, 1, tzinfo=UTC),
    columns=[STAGE, TAGS, NAME],
)


def test_a_choice_is_written_by_its_label_whatever_its_case():
    keyed = column_keyed(TABLE, {"Stage": " won ", str(TAGS.id): ["Lost", str(WON)]})
    assert keyed == {str(STAGE.id): str(WON), str(TAGS.id): [str(LOST), str(WON)]}


def test_what_names_no_live_option_is_left_for_the_validator_to_refuse():
    # An archived option takes no new values, so its label resolves to nothing.
    keyed = column_keyed(TABLE, {"Stage": "Old", "Tags": "Won", "Name": "Won"})
    assert keyed == {str(STAGE.id): "Old", str(TAGS.id): "Won", str(NAME.id): "Won"}
    with pytest.raises(CellProblem, match=r"options: Won, Lost$"):
        COLUMN_TYPES["single_select"].validate("Old", STAGE, True)


def test_a_record_reads_its_choices_by_label_an_archived_one_too():
    record = RecordRead(
        id=UUID("00000000-0000-4000-8000-0000000000c1"),
        table_id=TABLE.id,
        schema_version=1,
        revision=1,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        values={
            str(STAGE.id): str(OLD),
            str(TAGS.id): [str(WON), "gone"],
            str(NAME.id): "Acme",
            "dropped": 1,
        },
    )
    assert labelled(TABLE, record)["values"] == {
        "Stage": "Old",
        "Tags": ["Won", "gone"],
        "Name": "Acme",
        "dropped": 1,
    }


def test_a_filter_names_a_choice_by_its_label():
    unknown = UUID("00000000-0000-4000-8000-0000000000d1")
    filters = [
        RecordFilter(column_id=STAGE.id, op="eq", value="Won"),
        RecordFilter(column_id=TAGS.id, op="in", value=["Lost", "won"]),
        RecordFilter(column_id=STAGE.id, op="is_null", value=True),
        RecordFilter(column_id=NAME.id, op="eq", value="Won"),
        RecordFilter(column_id=unknown, op="eq", value="Won"),
    ]
    assert [condition.value for condition in filters_by_label(TABLE, filters)] == [
        str(WON),
        [str(LOST), str(WON)],
        True,
        "Won",
        "Won",
    ]
