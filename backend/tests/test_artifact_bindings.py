"""How a page query is said in words: the one wording publish and consent read.

`tests/integration/test_artifact_bindings.py` resolves real queries; this pins what
`disclose` says of one built by hand, including what a resolved query never holds
today - an order by a worked-out column - so the disclosure cannot drop it silently.
"""

from __future__ import annotations

import uuid

from app.schemas.artifact import ArtifactBinding, BindingReach
from app.schemas.virtual_table import ColumnDef, RecordSort
from app.services.artifact_bindings import disclose
from app.services.virtual_tables import TableSource


def _people() -> tuple[TableSource, dict[str, uuid.UUID]]:
    ids = {label: uuid.uuid4() for label in ("Name", "Salary", "Level", "Pay band")}
    columns = [
        ColumnDef(id=ids["Name"], label="Name", type="text"),
        ColumnDef(id=ids["Salary"], label="Salary", type="number"),
        ColumnDef(id=ids["Level"], label="Level", type="integer"),
        ColumnDef(
            id=ids["Pay band"], label="Pay band", type="formula", formula="{Salary} * {Level}"
        ),
    ]
    return TableSource(id=uuid.uuid4(), name="People", archived=False, columns=columns), ids


def _binding(source: TableSource, ids: dict[str, uuid.UUID], sort: RecordSort) -> ArtifactBinding:
    return ArtifactBinding(
        name="people",
        table_id=source.id,
        sort=sort,
        limit=100,
        fields={"name": ids["Name"]},
        reach=BindingReach(tables={source.id: dict.fromkeys(ids.values(), 0)}),
    )


def test_an_order_by_a_worked_out_column_says_what_it_reads():
    source, ids = _people()
    binding = _binding(source, ids, RecordSort(by=str(ids["Pay band"]), direction="desc"))

    said = disclose(binding, {source.id: source})

    assert said.sort == "Pay band (formula over Salary, Level), descending"
    assert said.fields == {"name": "Name (text)"}


def test_an_order_by_a_column_of_values_names_only_the_column():
    source, ids = _people()

    said = disclose(_binding(source, ids, RecordSort(by=str(ids["Salary"]))), {source.id: source})

    assert said.sort == "Salary, ascending"


def test_an_order_by_a_record_time_says_which():
    source, ids = _people()

    said = disclose(
        _binding(source, ids, RecordSort(by="updated_at", direction="desc")), {source.id: source}
    )

    assert said.sort == "when last changed, descending"
